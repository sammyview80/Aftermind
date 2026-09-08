"""Claude Code hook handlers, mirroring the same lifecycle the Hermes
adapter proves: recall before reasoning, observe after tool activity,
checkpoint on session end/compact.

Claude Code hooks are not in-process callbacks like Hermes' — each is a
separate `command` invocation per hooks.md, receiving one JSON object on
stdin and (optionally) printing JSON to stdout. This module holds the
per-event logic as plain functions (payload dict in, response dict/None
out) so integrations/claude_code/__main__.py — the actual process
entrypoint settings.json's `hooks` config points `command` at — stays a
thin dispatcher, and so these functions are unit-testable without going
through stdin/stdout at all.

Config (env vars, all optional):
    AFTERMIND_URL                REST base URL (default http://localhost:8000)
    AFTERMIND_SCOPE_TENANT/PROJECT/REPOSITORY/AGENT   scope overrides (scope_mapper.py)
    AFTERMIND_RECALL_TIMEOUT     seconds (default 3)
    AFTERMIND_RECALL_LIMIT       max memories per recall (default 5)
    AFTERMIND_OBSERVE_TIMEOUT    seconds (default 10)
    AFTERMIND_CHECKPOINT_TIMEOUT seconds (default 15)
"""
import os
import threading

import httpx

from integrations.claude_code.checkpoint_adapter import checkpoint_from_transcript
from integrations.claude_code.event_mapper import (
    observation_text_for_prompt,
    observation_text_for_tool_failure,
    observation_text_for_tool_use,
)
from integrations.claude_code.scope_mapper import derive_scope

DEFAULT_URL = "http://localhost:8000"
DEFAULT_RECALL_TIMEOUT = 3.0
DEFAULT_RECALL_LIMIT = 5
DEFAULT_OBSERVE_TIMEOUT = 10.0


def _base_url() -> str:
    return os.environ.get("AFTERMIND_URL", DEFAULT_URL).rstrip("/")


def observe_async(text: str, event_type: str, scope: dict) -> None:
    if not text or not text.strip():
        return
    timeout = float(os.environ.get("AFTERMIND_OBSERVE_TIMEOUT", DEFAULT_OBSERVE_TIMEOUT))

    def _post():
        try:
            httpx.post(
                f"{_base_url()}/observe",
                json={"scope": {"levels": scope}, "output": text, "event_type": event_type},
                timeout=timeout,
            )
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


def on_user_prompt_submit(payload: dict) -> dict | None:
    """recall() before reasoning, observe() the prompt itself — the
    Claude Code counterpart to Hermes' pre_llm_call. Injects context via
    hookSpecificOutput.additionalContext, exactly the shape hooks.md
    documents for this event; returns None (no output) on any failure
    or empty result so a hook error never blocks the user's turn."""
    text = observation_text_for_prompt(payload)
    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))

    observe_async(text, "user_message", scope)

    if not text:
        return None

    timeout = float(os.environ.get("AFTERMIND_RECALL_TIMEOUT", DEFAULT_RECALL_TIMEOUT))
    limit = int(os.environ.get("AFTERMIND_RECALL_LIMIT", DEFAULT_RECALL_LIMIT))
    try:
        response = httpx.post(
            f"{_base_url()}/recall",
            json={"scope": {"levels": scope}, "text": text, "limit": limit},
            timeout=timeout,
        )
        response.raise_for_status()
        context = response.json().get("context", "")
    except Exception:
        return None

    if not context.strip():
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"[Aftermind memory]\n{context}",
        }
    }


def on_session_start(payload: dict) -> dict | None:
    """Same context-injection contract as on_user_prompt_submit, fired
    once at session start/resume — so a resumed session recovers state
    even before the user types anything, matching the milestone's
    "recall before reasoning" on session start/new, not just per-turn."""
    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))
    timeout = float(os.environ.get("AFTERMIND_RECALL_TIMEOUT", DEFAULT_RECALL_TIMEOUT))
    limit = int(os.environ.get("AFTERMIND_RECALL_LIMIT", DEFAULT_RECALL_LIMIT))

    try:
        response = httpx.post(
            f"{_base_url()}/recall",
            json={"scope": {"levels": scope}, "text": "", "limit": limit},
            timeout=timeout,
        )
        response.raise_for_status()
        context = response.json().get("context", "")
    except Exception:
        return None

    if not context.strip():
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": f"[Aftermind memory]\n{context}",
        }
    }


def on_post_tool_use(payload: dict) -> None:
    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))
    event_type, text = observation_text_for_tool_use(payload)
    observe_async(text, event_type, scope)


def on_post_tool_use_failure(payload: dict) -> None:
    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))
    event_type, text = observation_text_for_tool_failure(payload)
    observe_async(text, event_type, scope)


def on_session_end(payload: dict) -> None:
    checkpoint_from_transcript(payload, reason="session_end")


def on_pre_compact(payload: dict) -> None:
    checkpoint_from_transcript(payload, reason="pre_compact")


HANDLERS = {
    "UserPromptSubmit": on_user_prompt_submit,
    "SessionStart": on_session_start,
    "PostToolUse": on_post_tool_use,
    "PostToolUseFailure": on_post_tool_use_failure,
    "SessionEnd": on_session_end,
    "PreCompact": on_pre_compact,
}
