import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_response(raw: str) -> Any:
    """Parse an LLM's JSON reply, tolerating ```json ... ``` code fences
    that models commonly wrap structured output in."""
    return json.loads(_FENCE_RE.sub("", raw.strip()))
