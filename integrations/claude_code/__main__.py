"""Process entrypoint a Claude Code hook `command` actually invokes:

    python3 -m integrations.claude_code

Reads one JSON payload from stdin (Claude Code's hook contract — see
hooks.md), dispatches on its `hook_event_name` to plugin.HANDLERS, and
prints any returned dict as JSON to stdout (Claude Code parses stdout
JSON for hookSpecificOutput; a handler returning None simply prints
nothing, which Claude Code treats as "no decision, continue normally").
Never raises: an unreachable Aftermind server, a malformed payload, or
an unknown event must never surface as a broken hook to the user.
"""
import json
import sys

from integrations.claude_code.plugin import HANDLERS


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    event_name = payload.get("hook_event_name", "")
    handler = HANDLERS.get(event_name)
    if handler is None:
        return 0

    try:
        result = handler(payload)
    except Exception:
        return 0

    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
