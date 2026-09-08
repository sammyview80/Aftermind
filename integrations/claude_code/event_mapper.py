"""Maps Claude Code hook payload shapes (verified against the real
hooks.md contract: UserPromptSubmit gives `prompt`; PostToolUse gives
`tool_name`/`tool_input`/`tool_response`; PostToolUseFailure gives
`tool_name`/`tool_input`/`error`) onto Aftermind's
framework-neutral event vocabulary."""
from typing import Any

DEFAULT_MAX_CHARS = 500

# Claude Code delivers some machine-generated turns through the same
# UserPromptSubmit hook as real typed prompts: subagent task
# notifications, system reminders, the caveat wrapper around local
# command output, and slash commands. None of those are the user stating
# something worth remembering, and the notifications can run to many
# kilobytes — observing them verbatim once flooded a scope's recall with
# four audit reports at confidence 0.95.
_SYSTEM_PAYLOAD_PREFIXES = (
    "<task-notification>",
    "<system-reminder>",
    "<local-command-caveat>",
    "<command-name>",
    "<command-message>",
    "<local-command-stdout>",
    "[Request interrupted",
    "[Cross-session",
)


def is_system_payload(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return False
    if stripped.startswith("/") and " " not in stripped.split("\n", 1)[0].strip()[:2]:
        return True  # slash command such as /clear or /model
    return stripped.startswith(_SYSTEM_PAYLOAD_PREFIXES)


def observation_text_for_prompt(payload: dict[str, Any], max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """The user's prompt as observable text, or "" when it should not be
    observed at all (system payload, slash command, empty). Capped to
    `max_chars`, the same bound tool output gets — a memory candidate is
    a statement, not a transcript."""
    # Claude Code sends `prompt`; `user_prompt` kept as a legacy fallback.
    text = str(payload.get("prompt") or payload.get("user_prompt", "")).strip()
    if not text or is_system_payload(text):
        return ""
    return text[:max_chars]


def observation_text_for_tool_use(payload: dict[str, Any], max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str]:
    """Returns (event_type, text) for a PostToolUse payload. Claude
    Code's PostToolUse fires on tool success; a distinct
    PostToolUseFailure event covers failures — both map onto Aftermind's
    tool_completed/tool_failed, mirroring the Hermes adapter's
    observe_tool_result."""
    tool_name = payload.get("tool_name", "unknown_tool")
    # Claude Code sends `tool_response`; `tool_result` kept as a legacy fallback.
    result = payload.get("tool_response", payload.get("tool_result", ""))
    text = f"Tool {tool_name} result: {str(result)[:max_chars]}"
    return "tool_completed", text


def observation_text_for_tool_failure(payload: dict[str, Any], max_chars: int = DEFAULT_MAX_CHARS) -> tuple[str, str]:
    tool_name = payload.get("tool_name", "unknown_tool")
    # Claude Code sends `error` for PostToolUseFailure; older names kept as fallback.
    result = payload.get("error") or payload.get("tool_response") or payload.get("tool_result", "")
    text = f"Tool {tool_name} failed: {str(result)[:max_chars]}"
    return "tool_failed", text
