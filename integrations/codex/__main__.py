"""Process entrypoint for Codex hooks:

    python -m integrations.codex                      # hook mode (stdin JSON)
    python -m integrations.codex --checkpoint REASON  # detached checkpoint child

Never raises: an unreachable Aftermind server, a malformed payload, or
an unknown event must never surface as a broken hook.
"""
import json
import sys

from integrations.codex.plugin import HANDLERS, run_checkpoint


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    if len(argv) >= 2 and argv[0] == "--checkpoint":
        try:
            run_checkpoint(payload, argv[1])
        except Exception:  # noqa: BLE001
            pass
        return 0

    handler = HANDLERS.get(payload.get("hook_event_name", ""))
    if handler is None:
        return 0
    try:
        result = handler(payload)
    except Exception:  # noqa: BLE001
        return 0
    if result:
        print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
