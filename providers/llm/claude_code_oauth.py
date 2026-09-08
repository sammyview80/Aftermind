"""LLMProvider that reuses the Claude Code login (Claude subscription).

Anthropic Messages API with the Claude Code OAuth access token as a
Bearer credential. OAuth traffic must identify as Claude Code: the
`claude-code-20250219,oauth-2025-04-20` betas, `x-app: cli`, a
claude-cli user agent, and a system prompt that starts with Claude Code's
identity line — otherwise Anthropic rejects or intermittently 500s the
request (documented in Hermes' agent/anthropic_adapter.py, which this
mirrors). Tokens come from the Keychain / ~/.claude/.credentials.json,
refreshed via platform.claude.com/v1/oauth/token when stale; refreshed
pairs are kept in Aftermind's own store, not written back to Claude Code.
Standard library only.
"""
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

from providers.llm.base import BaseLLMProvider
from providers.llm.credentials import ANTHROPIC_BASE_URL, claude_code_token_valid, read_claude_code_credentials
from providers.llm.token_store import TokenStore

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT = 120
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_TOKEN_URLS = ("https://platform.claude.com/v1/oauth/token", "https://console.anthropic.com/v1/oauth/token")
OAUTH_BETAS = "claude-code-20250219,oauth-2025-04-20"
CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."
_VERSION_FALLBACK = "2.1.74"
_version_cache: Optional[str] = None


def claude_code_version() -> str:
    """Installed Claude Code version for the user agent (Anthropic rejects
    versions too far behind the current release)."""
    global _version_cache
    if _version_cache is None:
        _version_cache = _VERSION_FALLBACK
        try:
            result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
            first = (result.stdout or "").strip().split()
            if result.returncode == 0 and first and first[0][0].isdigit():
                _version_cache = first[0]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return _version_cache


def refresh_claude_code_tokens(refresh_token: str, opener: Callable = urllib.request.urlopen, timeout: float = 15) -> dict:
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": OAUTH_CLIENT_ID}
    ).encode()
    last_error: Optional[Exception] = None
    for url in OAUTH_TOKEN_URLS:
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": f"claude-cli/{claude_code_version()} (external, cli)"},
            method="POST",
        )
        try:
            with opener(request, timeout=timeout) as response:
                payload = json.loads(response.read())
        except Exception as exc:  # noqa: BLE001 - try the next endpoint
            last_error = exc
            continue
        if not payload.get("access_token"):
            raise RuntimeError("Claude Code token refresh returned no access_token")
        return {
            "accessToken": payload["access_token"],
            "refreshToken": payload.get("refresh_token") or refresh_token,
            "expiresAt": int(time.time() * 1000) + int(payload.get("expires_in", 3600)) * 1000,
            "source": "aftermind_refresh",
        }
    raise RuntimeError(f"Claude Code token refresh failed: {last_error}")


class ClaudeCodeOAuthProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = ANTHROPIC_BASE_URL,
        access_token: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        token_store: Optional[TokenStore] = None,
        opener: Callable = urllib.request.urlopen,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self._fixed_token = access_token  # CLAUDE_CODE_OAUTH_TOKEN style, no refresh
        self._store = token_store or TokenStore()
        self._opener = opener
        self._timeout = timeout

    def _access_token(self) -> str:
        if self._fixed_token:
            return self._fixed_token
        cli = read_claude_code_credentials()
        ours = self._store.get("claude_code_oauth")
        for creds in (cli, ours):
            if creds and creds.get("accessToken") and claude_code_token_valid(creds):
                return creds["accessToken"]
        refresh = (ours or {}).get("refreshToken") or (cli or {}).get("refreshToken")
        if not refresh:
            raise ValueError("No Claude Code login found (run `claude` and log in, then `aftermind init`)")
        refreshed = refresh_claude_code_tokens(refresh, opener=self._opener)
        self._store.set("claude_code_oauth", refreshed)
        return refreshed["accessToken"]

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "anthropic-beta": OAUTH_BETAS,
            "x-app": "cli",
            "User-Agent": f"claude-cli/{claude_code_version()} (external, cli)",
            "Content-Type": "application/json",
        }

    def complete(self, prompt: str) -> str:
        token = self._access_token()
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": [{"type": "text", "text": CLAUDE_CODE_SYSTEM_PREFIX}],
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode()
        request = urllib.request.Request(f"{self.base_url}/v1/messages", data=body, headers=self._headers(token), method="POST")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300] if hasattr(exc, "read") else ""
            raise RuntimeError(f"Claude Code OAuth request failed ({exc.code}): {detail}") from exc
        return "".join(block.get("text", "") for block in payload.get("content", []) if block.get("type") == "text")
