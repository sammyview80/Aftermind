"""Hermes plugin: recall Aftermind memory before each turn, observe
activity after each turn/tool call.

Install: drop (or symlink) this directory at ~/.hermes/plugins/aftermind/,
then add "aftermind" to plugins.enabled in ~/.hermes/config.yaml.

Milestone 1 (pre_llm_call -> recall -> inject context) plus milestone 2
(post_llm_call/post_tool_call -> observe). Checkpoint on session end/
reset/handoff is the next milestone, not wired yet.

Config (env vars, all optional):
    AFTERMIND_URL            REST base URL (default http://localhost:8000)
    AFTERMIND_SCOPE_TENANT   scope tenant_id level (default "hermes")
    AFTERMIND_SCOPE_PROJECT  scope project_id level (default "aftermind")
    AFTERMIND_RECALL_TIMEOUT seconds (default 3)
    AFTERMIND_RECALL_LIMIT   max memories per recall (default 5)
    AFTERMIND_OBSERVE_TIMEOUT seconds (default 10 — reconciliation calls
                               an LLM, slower than recall)
    AFTERMIND_TOOL_RESULT_MAX_CHARS truncation for tool result text
                               (default 500)
"""
import os
import threading

import httpx

DEFAULT_URL = "http://localhost:8000"
DEFAULT_RECALL_TIMEOUT = 3.0
DEFAULT_RECALL_LIMIT = 5
DEFAULT_OBSERVE_TIMEOUT = 10.0
DEFAULT_TOOL_RESULT_MAX_CHARS = 500


def _scope() -> dict:
    return {
        "tenant_id": os.environ.get("AFTERMIND_SCOPE_TENANT", "hermes"),
        "project_id": os.environ.get("AFTERMIND_SCOPE_PROJECT", "aftermind"),
    }


def _base_url() -> str:
    return os.environ.get("AFTERMIND_URL", DEFAULT_URL).rstrip("/")


def recall(session_id: str, user_message: str, is_first_turn: bool, **kwargs) -> dict | str | None:
    """pre_llm_call callback: fetch Aftermind's recall context for this
    turn's message and inject it. Best-effort — any failure (Aftermind
    down, network issue, bad response) returns None rather than blocking
    or breaking the user's turn, same contract as Hermes' own documented
    memory-recall example.
    """
    if not user_message or not user_message.strip():
        return None

    timeout = float(os.environ.get("AFTERMIND_RECALL_TIMEOUT", DEFAULT_RECALL_TIMEOUT))
    limit = int(os.environ.get("AFTERMIND_RECALL_LIMIT", DEFAULT_RECALL_LIMIT))

    try:
        response = httpx.post(
            f"{_base_url()}/recall",
            json={"scope": {"levels": _scope()}, "text": user_message, "limit": limit},
            timeout=timeout,
        )
        response.raise_for_status()
        context = response.json().get("context", "")
    except Exception:
        return None

    if not context.strip():
        return None

    return {"context": f"[Aftermind memory]\n{context}"}


def observe(text: str, event_type: str) -> None:
    """POST one piece of activity to Aftermind's /observe. Synchronous —
    callers that don't want to block a turn should run this in a thread
    (see observe_async). Swallows all errors: an unreachable Aftermind
    server must never break a Hermes turn."""
    if not text or not text.strip():
        return

    timeout = float(os.environ.get("AFTERMIND_OBSERVE_TIMEOUT", DEFAULT_OBSERVE_TIMEOUT))
    try:
        httpx.post(
            f"{_base_url()}/observe",
            json={"scope": {"levels": _scope()}, "output": text, "event_type": event_type},
            timeout=timeout,
        )
    except Exception:
        pass


def observe_async(text: str, event_type: str) -> None:
    """Fire-and-forget observe() in a daemon thread. Reconciliation calls
    an LLM and can take a few seconds — never let that add latency to a
    Hermes turn, matching the non-blocking contract Hermes documents for
    its own memory-provider sync_turn()."""
    threading.Thread(target=observe, args=(text, event_type), daemon=True).start()


def observe_turn(session_id: str, user_message: str, assistant_response: str, **kwargs) -> None:
    """post_llm_call callback: capture the user's message and the
    assistant's response as two separate observations — a trivial
    exchange on either side is filtered out downstream by Aftermind's
    own candidate extractor, not guessed at here."""
    observe_async(user_message, "user_message")
    observe_async(assistant_response, "agent_message")


def observe_tool_result(**kwargs) -> None:
    """post_tool_call callback. Hermes' own docs disagree on whether the
    arguments dict is passed as `params` (plugins.md's minimal example)
    or `args` (the hooks.md catalog table) — read everything from
    **kwargs instead of declaring named parameters, so a naming mismatch
    can't turn into a silently-skipped TypeError (per Hermes' own rule:
    callback exceptions are logged and skipped, not raised).
    Truncated to avoid flooding Aftermind with large tool output."""
    tool_name = kwargs.get("tool_name", "unknown_tool")
    status = kwargs.get("status")
    result = kwargs.get("result")

    max_chars = int(os.environ.get("AFTERMIND_TOOL_RESULT_MAX_CHARS", DEFAULT_TOOL_RESULT_MAX_CHARS))
    text = str(result)[:max_chars]

    event_type = "tool_failed" if status == "error" else "tool_completed"
    observe_async(f"Tool {tool_name} result: {text}", event_type)


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", recall)
    ctx.register_hook("post_llm_call", observe_turn)
    ctx.register_hook("post_tool_call", observe_tool_result)
