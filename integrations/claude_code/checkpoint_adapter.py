"""Session-boundary checkpointing for Claude Code: SessionEnd and
PreCompact are the two hooks that fire at a natural "stopping point"
(session teardown, and about-to-lose-context-to-compaction) — both read
the transcript for the last exchange and POST it to
/checkpoint/from-text, same endpoint the Hermes adapter uses.
"""
import os

import httpx

from integrations.claude_code.scope_mapper import derive_scope
from integrations.claude_code.transcript import count_exchanges, read_last_exchange

DEFAULT_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 15.0
# A session with fewer real exchanges than this has nothing to hand off;
# checkpointing it would only overwrite a good earlier checkpoint with
# "placeholder conversation" (seen live: v1 replaced by three trivial
# one-prompt headless sessions).
DEFAULT_MIN_EXCHANGES = 2


def _base_url() -> str:
    return os.environ.get("AFTERMIND_URL", DEFAULT_URL).rstrip("/")


def checkpoint_from_transcript(payload: dict, reason: str) -> None:
    """Best-effort: swallows all errors, same contract as the Hermes
    adapter's _checkpoint_from_pending — an unreachable Aftermind server
    or an unparsable transcript must never break a Claude Code hook."""
    transcript_path = payload.get("transcript_path")
    min_exchanges = int(os.environ.get("AFTERMIND_CHECKPOINT_MIN_EXCHANGES", DEFAULT_MIN_EXCHANGES))
    if count_exchanges(transcript_path) < min_exchanges:
        return

    text = read_last_exchange(transcript_path)
    if not text:
        return

    scope = derive_scope(cwd=payload.get("cwd"), session_id=payload.get("session_id"))
    timeout = float(os.environ.get("AFTERMIND_CHECKPOINT_TIMEOUT", DEFAULT_TIMEOUT))

    try:
        httpx.post(
            f"{_base_url()}/checkpoint/from-text",
            json={"scope": {"levels": scope}, "text": text, "reason": reason},
            timeout=timeout,
        )
    except Exception:
        pass
