"""Reads the last user/assistant exchange out of a Claude Code session
transcript (JSONL at the `transcript_path` every hook payload carries),
for turning into freeform text for /checkpoint/from-text.

Schema verified against a real transcript file, not guessed: each line
is a JSON object with a `type` field — "user" and "assistant" lines
carry a `message` field shaped like the Anthropic Messages API. A user
message's `content` is usually a plain string; an assistant message's
`content` is a list of blocks (`thinking`, `text`, `tool_use`, ...) —
only `text` blocks are prose worth summarizing.
"""
import json
from pathlib import Path
from typing import Optional


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    return ""


def read_last_exchange(transcript_path: Optional[str], max_lines: int = 200) -> str:
    """The most recent user message and the most recent assistant text
    reply from the transcript, formatted as "User: ...\\nAssistant: ...".
    Best-effort: a missing/unreadable/empty-of-text transcript returns
    "" rather than raising — checkpointing from freeform text is a
    nice-to-have observation, not something that should ever break a
    Claude Code hook.
    """
    if not transcript_path:
        return ""

    path = Path(transcript_path)
    if not path.exists():
        return ""

    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""

    last_user = ""
    last_assistant = ""
    for line in reversed(lines[-max_lines:]):
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        entry_type = entry.get("type")
        message = entry.get("message")
        if not isinstance(message, dict):
            continue

        if entry_type == "assistant" and not last_assistant:
            last_assistant = _message_text(message)
        elif entry_type == "user" and not last_user:
            last_user = _message_text(message)

        if last_user and last_assistant:
            break

    parts = []
    if last_user:
        parts.append(f"User: {last_user}")
    if last_assistant:
        parts.append(f"Assistant: {last_assistant}")
    return "\n".join(parts)
