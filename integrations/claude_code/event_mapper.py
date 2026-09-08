"""Maps Claude Code hook payload shapes (verified against the real
hooks.md contract: UserPromptSubmit gives `user_prompt`; PostToolUse
gives `tool_name`/`tool_input`/`tool_result`) onto Aftermind's
framework-neutral event vocabulary."""
from typing import Any


def observation_text_for_prompt(payload: dict[str, Any]) -> str:
    return str(payload.get("user_prompt", "")).strip()


def observation_text_for_tool_use(payload: dict[str, Any], max_chars: int = 500) -> tuple[str, str]:
    """Returns (event_type, text) for a PostToolUse payload. Claude
    Code's PostToolUse fires on tool success; a distinct
    PostToolUseFailure event covers failures — both map onto Aftermind's
    tool_completed/tool_failed, mirroring the Hermes adapter's
    observe_tool_result."""
    tool_name = payload.get("tool_name", "unknown_tool")
    result = payload.get("tool_result", "")
    text = f"Tool {tool_name} result: {str(result)[:max_chars]}"
    return "tool_completed", text


def observation_text_for_tool_failure(payload: dict[str, Any], max_chars: int = 500) -> tuple[str, str]:
    tool_name = payload.get("tool_name", "unknown_tool")
    result = payload.get("tool_result", payload.get("error", ""))
    text = f"Tool {tool_name} failed: {str(result)[:max_chars]}"
    return "tool_failed", text
