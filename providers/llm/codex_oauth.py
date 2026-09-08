"""LLMProvider that reuses the Codex CLI's ChatGPT login.

Talks to the same backend the Codex CLI uses
(https://chatgpt.com/backend-api/codex, Responses API) with the OAuth
access token from ~/.codex/auth.json. Required identity headers and the
refresh flow (auth.openai.com/oauth/token, client_id
app_EMoamEEZ73f0CkXaXp7hrann) follow the Codex CLI / Hermes
implementation. Refreshed tokens are kept in Aftermind's own token store,
never written back into ~/.codex/auth.json.
"""
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

from providers.llm.base import BaseLLMProvider
from providers.llm.credentials import CODEX_BASE_URL, codex_account_id, jwt_expired, read_codex_auth
from providers.llm.token_store import TokenStore

CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
# ChatGPT-account Codex rejects the public-API "-mini" slugs; gpt-5.5 is in
# the account catalog (`aftermind init` offers the live list).
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_TIMEOUT = 120
_USER_AGENT = "aftermind/0.1 (codex_cli_rs compatible)"


def refresh_codex_tokens(refresh_token: str, opener: Callable = urllib.request.urlopen, timeout: float = 20) -> dict:
    """OAuth refresh_token grant against OpenAI's auth server. Returns the
    new {access_token, refresh_token, id_token?}."""
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": CODEX_OAUTH_CLIENT_ID}
    ).encode()
    request = urllib.request.Request(
        CODEX_OAUTH_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": _USER_AGENT},
        method="POST",
    )
    with opener(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    if not payload.get("access_token"):
        raise RuntimeError("Codex token refresh returned no access_token")
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token") or refresh_token,
        "id_token": payload.get("id_token", ""),
        "refreshed_at": int(time.time()),
    }


class CodexOAuthProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str = CODEX_BASE_URL,
        token_store: Optional[TokenStore] = None,
        client_factory: Optional[Callable[..., Any]] = None,
        opener: Callable = urllib.request.urlopen,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._store = token_store or TokenStore()
        self._client_factory = client_factory
        self._opener = opener
        self._timeout = timeout

    # ---------------------------------------------------------- tokens

    def _current_tokens(self) -> dict:
        """Freshest usable pair: the CLI's file if its token is valid,
        else our refreshed pair, else refresh whichever refresh_token we
        have. Rejects the exact case Hermes warns about — adopting a stale
        pair with no working refresh token."""
        cli = (read_codex_auth() or {}).get("tokens") or {}
        ours = self._store.get("codex_oauth") or {}
        for tokens in (cli, ours):
            access = tokens.get("access_token", "")
            if access and jwt_expired(access) is False:
                return tokens
        # Prefer our refresh token: if we refreshed once, the CLI's old
        # refresh token has been rotated out.
        refresh = ours.get("refresh_token") or cli.get("refresh_token")
        if not refresh:
            raise ValueError("No Codex login found (run `codex login`, then `aftermind init`)")
        refreshed = refresh_codex_tokens(refresh, opener=self._opener)
        self._store.set("codex_oauth", refreshed)
        return refreshed

    def _headers(self, access_token: str) -> dict[str, str]:
        headers = {"User-Agent": _USER_AGENT, "originator": "codex_cli_rs"}
        account = codex_account_id(access_token)
        if account:
            headers["ChatGPT-Account-ID"] = account
        return headers

    # -------------------------------------------------------- complete

    def _client(self, access_token: str):
        if self._client_factory is not None:
            return self._client_factory(api_key=access_token, base_url=self.base_url, default_headers=self._headers(access_token))
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError("CodexOAuthProvider requires the 'openai' package: pip install openai") from exc
        return OpenAI(api_key=access_token, base_url=self.base_url, default_headers=self._headers(access_token), timeout=self._timeout, max_retries=1)

    def complete(self, prompt: str) -> str:
        tokens = self._current_tokens()
        client = self._client(tokens["access_token"])
        # The Codex backend serves the Responses API in streaming mode with
        # store=false (it has no server-side conversation state for third
        # parties) — same call shape the Codex CLI itself issues.
        stream = client.responses.create(
            model=self.model,
            instructions="You are a precise assistant. Follow the user's output format exactly.",
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            store=False,
            stream=True,
        )
        chunks: list[str] = []
        for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                chunks.append(getattr(event, "delta", "") or "")
            elif event_type == "response.failed":
                error = getattr(getattr(event, "response", None), "error", None)
                raise RuntimeError(f"Codex response failed: {error}")
        return "".join(chunks)
