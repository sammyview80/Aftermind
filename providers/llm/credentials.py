"""Discover LLM credentials already present on this machine so setup can
offer "use your existing Codex / Claude Code / OpenRouter login" instead
of asking for yet another key — the same convenience Hermes provides.

Sources (read-only, nothing here mutates the other tools' files):
    ~/.codex/auth.json               Codex CLI: ChatGPT OAuth tokens, or OPENAI_API_KEY
    ~/.claude/.credentials.json      Claude Code OAuth (claudeAiOauth)
    macOS Keychain                   Claude Code >= 2.1.114 ("Claude Code-credentials")
    environment / ~/.hermes/.env     OPENROUTER_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
                                     CLAUDE_CODE_OAUTH_TOKEN, LLM_API_KEY

Shapes and locations were verified against the installed tools and the
Hermes implementation (hermes_cli/auth.py, agent/anthropic_adapter.py),
not guessed.
"""
import base64
import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# provider ids understood by providers/llm/factory.py
OPENAI_COMPATIBLE = "openai_compatible"
CODEX_OAUTH = "codex_oauth"
CLAUDE_CODE_OAUTH = "claude_code_oauth"

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
ANTHROPIC_BASE_URL = "https://api.anthropic.com"

DEFAULT_CODEX_MODELS = ("gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.3-codex")
DEFAULT_CLAUDE_MODELS = ("claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001")
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class Credential:
    """One usable way to reach an LLM. `secret` is the key/token itself for
    API keys; for OAuth providers it is left empty (the provider reads and
    refreshes tokens itself) and `source` says where they live."""

    id: str  # e.g. "codex_oauth", "claude_code_oauth", "openrouter_env"
    provider: str  # factory id: openai_compatible | codex_oauth | claude_code_oauth
    label: str  # human line shown in the picker
    source: str  # where it was found
    base_url: str = ""
    models: tuple[str, ...] = field(default_factory=tuple)
    secret: str = ""
    account: str = ""  # email / account id when known, for the picker


# ------------------------------------------------------------- helpers


def jwt_claims(token: str) -> dict:
    """Decode a JWT payload without verifying (we only need display/routing
    claims such as chatgpt_account_id and exp). {} on any parse error."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def jwt_expired(token: str, skew_seconds: int = 60) -> Optional[bool]:
    """True/False from the token's exp claim; None when there is no exp."""
    exp = jwt_claims(token).get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return time.time() + skew_seconds >= exp


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text()
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# --------------------------------------------------------------- codex


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


def read_codex_auth(home: Optional[Path] = None) -> Optional[dict]:
    """Raw ~/.codex/auth.json: {auth_mode, OPENAI_API_KEY, tokens{id_token,
    access_token, refresh_token, account_id}, last_refresh}."""
    path = (home or codex_home()) / "auth.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def codex_account_id(access_token: str) -> Optional[str]:
    """`chatgpt_account_id` claim — the Codex backend needs it as the
    ChatGPT-Account-ID header."""
    value = jwt_claims(access_token).get("https://api.openai.com/auth", {})
    account = value.get("chatgpt_account_id") if isinstance(value, dict) else None
    return account if isinstance(account, str) and account else None


def codex_account_email(access_token: str) -> str:
    claims = jwt_claims(access_token)
    profile = claims.get("https://api.openai.com/profile", {})
    email = profile.get("email") if isinstance(profile, dict) else None
    return email if isinstance(email, str) else ""


# ---------------------------------------------------------- claude code


def read_claude_code_credentials_file(home: Optional[Path] = None) -> Optional[dict]:
    path = (home or Path.home()) / ".claude" / ".credentials.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return None
    return {
        "accessToken": oauth["accessToken"],
        "refreshToken": oauth.get("refreshToken", ""),
        "expiresAt": oauth.get("expiresAt", 0),
        "source": "claude_code_credentials_file",
    }


def read_claude_code_credentials_keychain(runner: Callable = subprocess.run) -> Optional[dict]:
    """macOS Keychain entry "Claude Code-credentials"; its password is the
    same claudeAiOauth JSON the file holds."""
    if platform.system() != "Darwin":
        return None
    try:
        result = runner(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True,
            text=True,
            timeout=5,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout.strip())
    except ValueError:
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return None
    return {
        "accessToken": oauth["accessToken"],
        "refreshToken": oauth.get("refreshToken", ""),
        "expiresAt": oauth.get("expiresAt", 0),
        "source": "macos_keychain",
    }


def claude_code_token_valid(creds: dict, skew_ms: int = 60_000) -> bool:
    expires_at = creds.get("expiresAt") or 0
    if not expires_at:
        return True  # unknown expiry: let the request decide
    return int(time.time() * 1000) < int(expires_at) - skew_ms


def read_claude_code_credentials(home: Optional[Path] = None, runner: Callable = subprocess.run) -> Optional[dict]:
    """Keychain and file, preferring whichever is still valid, then the
    one with the later expiry (Claude Code may refresh one and not the
    other) — same reconciliation Hermes does."""
    candidates = [c for c in (read_claude_code_credentials_keychain(runner), read_claude_code_credentials_file(home)) if c]
    if not candidates:
        return None
    valid = [c for c in candidates if claude_code_token_valid(c)]
    pool = valid or candidates
    return max(pool, key=lambda c: int(c.get("expiresAt") or 0))


# ------------------------------------------------------------ discovery


def discover_credentials(
    env: Optional[dict[str, str]] = None,
    home: Optional[Path] = None,
    hermes_home: Optional[Path] = None,
    keychain_runner: Callable = subprocess.run,
    include_keychain: bool = True,
) -> list[Credential]:
    """Everything usable on this machine, most convenient first: existing
    OAuth logins (no key to paste) before API keys found in env files."""
    env = dict(os.environ if env is None else env)
    home = home or Path.home()
    hermes_home = hermes_home or (home / ".hermes")
    hermes_env = read_env_file(hermes_home / ".env")

    def lookup(name: str) -> tuple[str, str]:
        if env.get(name):
            return env[name], f"environment ${name}"
        if hermes_env.get(name):
            return hermes_env[name], f"~/.hermes/.env {name}"
        return "", ""

    found: list[Credential] = []

    codex = read_codex_auth(home / ".codex" if "CODEX_HOME" not in env else Path(env["CODEX_HOME"]))
    if codex:
        tokens = codex.get("tokens") or {}
        access, refresh = tokens.get("access_token", ""), tokens.get("refresh_token", "")
        if access and refresh:
            email = codex_account_email(access)
            expired = jwt_expired(access)
            state = " (token expired, will refresh)" if expired else ""
            found.append(
                Credential(
                    id="codex_oauth",
                    provider=CODEX_OAUTH,
                    label=f"Codex CLI login (ChatGPT{': ' + email if email else ''}){state}",
                    source="~/.codex/auth.json",
                    base_url=CODEX_BASE_URL,
                    models=DEFAULT_CODEX_MODELS,
                    account=email,
                )
            )
        if codex.get("OPENAI_API_KEY"):
            found.append(
                Credential(
                    id="codex_openai_key",
                    provider=OPENAI_COMPATIBLE,
                    label="OpenAI API key stored by Codex CLI",
                    source="~/.codex/auth.json OPENAI_API_KEY",
                    base_url=OPENAI_BASE_URL,
                    models=(DEFAULT_OPENAI_MODEL,),
                    secret=codex["OPENAI_API_KEY"],
                )
            )

    claude = read_claude_code_credentials(home, keychain_runner if include_keychain else _no_keychain)
    if claude:
        state = "" if claude_code_token_valid(claude) else " (token expired, will refresh)"
        found.append(
            Credential(
                id="claude_code_oauth",
                provider=CLAUDE_CODE_OAUTH,
                label=f"Claude Code login (Claude subscription){state}",
                source="~/.claude/.credentials.json" if claude["source"] != "macos_keychain" else "macOS Keychain",
                base_url=ANTHROPIC_BASE_URL,
                models=DEFAULT_CLAUDE_MODELS,
            )
        )

    token, source = lookup("CLAUDE_CODE_OAUTH_TOKEN")
    if token:
        found.append(
            Credential(
                id="claude_code_oauth_token_env",
                provider=CLAUDE_CODE_OAUTH,
                label="Claude Code OAuth token from environment",
                source=source,
                base_url=ANTHROPIC_BASE_URL,
                models=DEFAULT_CLAUDE_MODELS,
                secret=token,
            )
        )

    for name, provider, label, base_url, models in (
        ("OPENROUTER_API_KEY", OPENAI_COMPATIBLE, "OpenRouter API key", OPENROUTER_BASE_URL, (DEFAULT_OPENROUTER_MODEL,)),
        ("OPENAI_API_KEY", OPENAI_COMPATIBLE, "OpenAI API key", OPENAI_BASE_URL, (DEFAULT_OPENAI_MODEL,)),
        ("ANTHROPIC_API_KEY", OPENAI_COMPATIBLE, "Anthropic API key", ANTHROPIC_BASE_URL + "/v1", DEFAULT_CLAUDE_MODELS),
        ("LLM_API_KEY", OPENAI_COMPATIBLE, "Existing LLM_API_KEY", env.get("LLM_BASE_URL", OPENROUTER_BASE_URL), ()),
    ):
        secret, src = lookup(name)
        if secret and not any(c.secret == secret for c in found):
            found.append(
                Credential(
                    id=name.lower(),
                    provider=provider,
                    label=label,
                    source=src,
                    base_url=base_url,
                    models=models,
                    secret=secret,
                )
            )
    return found


def _no_keychain(*args, **kwargs):  # noqa: ANN002, ANN003
    raise OSError("keychain disabled")
