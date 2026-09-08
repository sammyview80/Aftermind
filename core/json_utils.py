import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_response(raw: str) -> Any:
    """Parse an LLM's JSON reply, tolerating ```json ... ``` code fences
    that models commonly wrap structured output in, and one common
    real-model glitch: a trailing string value missing its closing quote
    before the final `}`/`]`."""
    text = _FENCE_RE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_repair_missing_closing_quote(text))


def _repair_missing_closing_quote(text: str) -> str:
    stripped = text.rstrip()
    if not stripped or stripped[-1] not in "}]":
        return text
    closer = stripped[-1]
    body = stripped[:-1].rstrip()
    if body.endswith('"'):
        return text  # already well-formed; the failure was something else
    return f'{body}"{closer}'
