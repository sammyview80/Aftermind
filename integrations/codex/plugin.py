"""Codex CLI hook handlers.

Codex's lifecycle hooks (learn.chatgpt.com/docs/hooks, verified) use the
same contract as Claude Code's: one JSON object on stdin carrying
`hook_event_name`, `session_id`, `cwd`, `transcript_path`, plus
`prompt` (UserPromptSubmit), `tool_name`/`tool_response` (PostToolUse),
`last_assistant_message` (Stop); a JSON object on stdout with
`hookSpecificOutput.additionalContext` injects context. So this adapter
reuses the Claude Code handlers and adds the two Codex-specific bits:

- `Stop` carries the assistant's final message — observe it (Codex has
  no PostToolUseFailure; tool errors surface in tool_response instead).
- `SessionEnd` hooks are capped at 3 seconds, far less than a checkpoint
  summarization takes, so the checkpoint runs in a detached child.

Config: same AFTERMIND_* env vars as integrations/claude_code/plugin.py.
Install: `aftermind connect codex` (registers the HTTP MCP server and
merges integrations/codex/hooks.snippet.json into ~/.codex/hooks.json).
"""
import json
import subprocess
import sys

from integrations.claude_code.checkpoint_adapter import checkpoint_from_transcript
from integrations.claude_code.plugin import (
    observe_async,
    on_post_tool_use,
    on_session_start,
    on_user_prompt_submit,
)
from integrations.claude_code.scope_mapper import derive_scope

DEFAULT_MAX_CHARS = 500


def on_stop(payload: dict) -> None:
    text = str(payload.get("last_assistant_message") or "").strip()
    if not text:
        return
    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))
    observe_async(text[:DEFAULT_MAX_CHARS], "agent_message", scope)


def _checkpoint_detached(payload: dict, reason: str) -> None:
    """Run the checkpoint in a child that outlives this hook process:
    Codex kills SessionEnd hooks after ~3s, the LLM summarization takes
    longer. The child gets the payload on stdin and is fully detached."""
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "integrations.codex", "--checkpoint", reason],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        child.stdin.write(json.dumps(payload).encode())  # type: ignore[union-attr]
        child.stdin.close()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - a hook must never fail the session
        pass


def on_session_end(payload: dict) -> None:
    _checkpoint_detached(payload, "session_end")


def on_pre_compact(payload: dict) -> None:
    _checkpoint_detached(payload, "pre_compact")


def run_checkpoint(payload: dict, reason: str) -> None:
    """Entry for the detached child: synchronous checkpoint."""
    checkpoint_from_transcript(payload, reason=reason)


def _with_event_name(handler, event_name: str):
    """Codex validates hookEventName in the output against the firing
    event; the reused Claude Code handlers already emit the right one for
    UserPromptSubmit/SessionStart, this keeps that explicit."""

    def wrapped(payload: dict):
        result = handler(payload)
        if isinstance(result, dict) and "hookSpecificOutput" in result:
            result["hookSpecificOutput"]["hookEventName"] = event_name
        return result

    return wrapped


HANDLERS = {
    "UserPromptSubmit": _with_event_name(on_user_prompt_submit, "UserPromptSubmit"),
    "SessionStart": _with_event_name(on_session_start, "SessionStart"),
    "PostToolUse": on_post_tool_use,
    "Stop": on_stop,
    "SessionEnd": on_session_end,
    "PreCompact": on_pre_compact,
}
