import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """One JSON object per log line. Trace lines (logger
    `aftermind.trace`) already carry a JSON payload as their message, so
    it is embedded as an object rather than double-encoded as a string."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        if record.name == "aftermind.trace":
            try:
                payload["trace"] = json.loads(message)
            except ValueError:
                payload["message"] = message
        else:
            payload["message"] = message
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Process-wide logging for the API/worker/CLI entry points. `fmt`
    is "json" (one object per line, for log shippers) or "text" (human
    readable, for a terminal). Idempotent: re-running replaces the root
    handler rather than stacking duplicates."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    if fmt.lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
