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


_TEXT_BLOCK_TYPES = frozenset({"text", "input_text", "output_text"})
# Injected/system content that shows up as a "user" message but isn't one:
# hook context, tool results, Codex's AGENTS.md preamble and environment block.
_NON_TURN_PREFIXES = ("<", "# AGENTS.md instructions")


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") in _TEXT_BLOCK_TYPES
        ).strip()
    return ""


def _role_and_message(entry: dict) -> tuple[str, dict] | None:
    """Normalize one transcript line to (role, message) for both formats:
    Claude Code (`type`: user|assistant, `message`: {...}) and Codex
    rollouts (`type`: response_item, `payload`: {role, content})."""
    message = entry.get("message")
    if isinstance(message, dict) and entry.get("type") in ("user", "assistant"):
        return entry["type"], message
    payload = entry.get("payload")
    if entry.get("type") == "response_item" and isinstance(payload, dict) and payload.get("role") in ("user", "assistant"):
        return payload["role"], payload
    return None


def _is_turn_text(text: str) -> bool:
    return bool(text) and not text.lstrip().startswith(_NON_TURN_PREFIXES)


def count_exchanges(transcript_path: Optional[str], max_lines: int = 2000) -> int:
    """How many real user/assistant exchanges the transcript holds — a
    user message with prose followed (at some point) by an assistant text
    reply. Hook-injected context, tool results and system lines don't
    count. Used to skip checkpointing a session that never did anything."""
    if not transcript_path:
        return 0
    path = Path(transcript_path)
    if not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return 0

    exchanges = 0
    awaiting_reply = False
    for line in lines[-max_lines:]:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        normalized = _role_and_message(entry)
        if normalized is None:
            continue
        role, message = normalized
        text = _message_text(message)
        if not _is_turn_text(text):
            continue  # tool results / injected system context, not a turn
        if role == "user":
            awaiting_reply = True
        elif role == "assistant" and awaiting_reply:
            exchanges += 1
            awaiting_reply = False
    return exchanges


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

        normalized = _role_and_message(entry)
        if normalized is None:
            continue
        role, message = normalized
        text = _message_text(message)
        if not _is_turn_text(text):
            continue

        if role == "assistant" and not last_assistant:
            last_assistant = text
        elif role == "user" and not last_user:
            last_user = text

        if last_user and last_assistant:
            break

    parts = []
    if last_user:
        parts.append(f"User: {last_user}")
    if last_assistant:
        parts.append(f"Assistant: {last_assistant}")
    return "\n".join(parts)
