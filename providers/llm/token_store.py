"""Aftermind's own store for OAuth tokens it has refreshed.

Both Codex and Claude Code rotate the refresh token on every refresh
and Hermes' experience (hermes_cli/auth.py, agent/anthropic_adapter.py)
is that writing back into the other tool's file is the wrong move: the
CLI owns that file and may be refreshing concurrently. So a refreshed
pair lives here, and lookup prefers whichever pair (ours or the CLI's)
is fresher. File is chmod 600.
"""
import json
import os
from pathlib import Path
from typing import Optional


def default_path() -> Path:
    return Path(os.environ.get("AFTERMIND_HOME") or (Path.home() / ".aftermind")) / "credentials.json"


class TokenStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or default_path()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, provider: str) -> Optional[dict]:
        entry = self._load().get(provider)
        return entry if isinstance(entry, dict) else None

    def set(self, provider: str, tokens: dict) -> None:
        data = self._load()
        data[provider] = tokens
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def clear(self, provider: str) -> None:
        data = self._load()
        if provider in data:
            del data[provider]
            self.path.write_text(json.dumps(data, indent=2))
