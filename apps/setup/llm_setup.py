"""`aftermind init`: interactive LLM setup that reuses what is already on
the machine.

    Found credentials:
      → 1. Codex CLI login (ChatGPT: you@example.com)      ~/.codex/auth.json
        2. Claude Code login (Claude subscription)         macOS Keychain
        3. OpenRouter API key                              ~/.hermes/.env OPENROUTER_API_KEY
        4. Enter a new API key (any OpenAI-compatible endpoint)
        5. Skip for now (recall works, observe() won't learn)

Picks a model (offering the provider's defaults), writes LLM_PROVIDER /
LLM_MODEL / LLM_BASE_URL / LLM_API_KEY to .env, and runs a one-line
completion to prove the choice works before saying so. Non-interactive
callers pass --provider/--model or --yes (first detected credential).
"""
import sys
from pathlib import Path
from typing import Callable, Optional

from apps.setup.stack import read_env_file, write_env_values
from providers.llm import credentials as creds
from providers.llm.credentials import Credential

Log = Callable[[str], None]
Ask = Callable[[str], str]


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        print(file=sys.stderr)
        return ""


def _choose(title: str, options: list[str], ask: Ask, log: Log, default: int = 0) -> Optional[int]:
    log("")
    log(title)
    for i, label in enumerate(options, start=1):
        marker = "→" if i - 1 == default else " "
        log(f"  {marker} {i}. {label}")
    raw = ask(f"  Choice [1-{len(options)}] ({default + 1}): ").strip()
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return int(raw) - 1
    return None


def _choose_model(credential: Credential, ask: Ask, log: Log, preset: Optional[str]) -> str:
    if preset:
        return preset
    models = list(credential.models)
    if credential.provider == creds.CODEX_OAUTH:
        live = fetch_codex_models()
        if live:
            models = live + [m for m in models if m not in live]
    options = [*models, "Type a model id"]
    idx = _choose("Model:", options, ask, log) if models else len(options) - 1
    if idx is None or idx == len(options) - 1:
        typed = ask("  Model id: ").strip()
        return typed or (models[0] if models else "")
    return options[idx]


def fetch_codex_models() -> list[str]:
    """Live catalog from the Codex backend for the logged-in account; []
    when unavailable (then the curated defaults are offered)."""
    try:
        import json
        import urllib.request

        auth = creds.read_codex_auth() or {}
        token = (auth.get("tokens") or {}).get("access_token", "")
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "aftermind/0.1"}
        account = creds.codex_account_id(token)
        if account:
            headers["ChatGPT-Account-ID"] = account
        request = urllib.request.Request(f"{creds.CODEX_BASE_URL}/models?client_version=1.0.0", headers=headers)
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read())
        entries = data.get("models", []) if isinstance(data, dict) else []
        ranked = sorted(
            (
                (int(e.get("priority", 10_000)) if isinstance(e.get("priority"), (int, float)) else 10_000, e["slug"].strip())
                for e in entries
                if isinstance(e, dict) and isinstance(e.get("slug"), str) and e.get("visibility", "") not in ("hide", "hidden")
            )
        )
        return [slug for _, slug in ranked]
    except Exception:  # noqa: BLE001
        return []


def env_updates_for(credential: Optional[Credential], model: str, api_key: str = "", base_url: str = "") -> dict[str, str]:
    """The .env keys a choice translates to. OAuth providers never get a
    key written — they resolve tokens at call time."""
    if credential is None:
        return {"LLM_PROVIDER": creds.OPENAI_COMPATIBLE, "LLM_BASE_URL": base_url or creds.OPENROUTER_BASE_URL, "LLM_API_KEY": api_key, "LLM_MODEL": model}
    updates = {"LLM_PROVIDER": credential.provider, "LLM_MODEL": model}
    if credential.provider == creds.OPENAI_COMPATIBLE:
        updates["LLM_BASE_URL"] = credential.base_url
        updates["LLM_API_KEY"] = credential.secret
    elif credential.id == "claude_code_oauth_token_env":
        updates["CLAUDE_CODE_OAUTH_TOKEN"] = credential.secret
    return updates


def verify(env_values: dict[str, str], log: Log) -> bool:
    """One tiny completion with the chosen provider. A failure here is a
    setup problem the user should see now, not a silent observe() later."""
    from providers.llm.factory import build_llm_provider

    merged = {**env_values}
    try:
        provider = build_llm_provider(merged)
        reply = provider.complete("Reply with exactly the single word OK.")
    except Exception as exc:  # noqa: BLE001
        log(f"  ✗ test call failed: {type(exc).__name__}: {str(exc)[:200]}")
        return False
    log(f"  ✓ test call ok ({merged.get('LLM_MODEL')}): {reply.strip()[:40]!r}")
    return True


def run(
    root: Path,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    assume_yes: bool = False,
    skip_verify: bool = False,
    ask: Ask = _ask,
    log: Log = _log,
    found: Optional[list[Credential]] = None,
) -> bool:
    """Returns True when .env ends up with a working (or at least chosen)
    LLM configuration."""
    env_path = root / ".env"
    current = read_env_file(env_path)
    found = creds.discover_credentials() if found is None else found

    chosen: Optional[Credential] = None
    api_key, base_url = "", ""

    if provider:
        matches = [c for c in found if c.provider == provider or c.id == provider]
        if provider == creds.OPENAI_COMPATIBLE and not matches:
            api_key, base_url = current.get("LLM_API_KEY", ""), current.get("LLM_BASE_URL", "")
        elif not matches:
            log(f"no credentials found for provider {provider!r}; run `aftermind init` interactively")
            return False
        else:
            chosen = matches[0]
    elif assume_yes:
        if not found:
            log("no existing credentials found and --yes given; leaving LLM unconfigured")
            return False
        chosen = found[0]
    else:
        log("== LLM setup ==")
        if found:
            log("Found credentials on this machine:")
        options = [f"{c.label:<52} {c.source}" for c in found]
        options.append("Enter a new API key (any OpenAI-compatible endpoint)")
        options.append("Skip for now (recall works, observe() will not learn)")
        idx = _choose("Use for Aftermind's reconciliation/consolidation LLM:", options, ask, log)
        if idx is None or idx == len(options) - 1:
            log("skipped LLM setup")
            return False
        if idx == len(options) - 2:
            base_url = ask(f"  Base URL [{creds.OPENROUTER_BASE_URL}]: ").strip() or creds.OPENROUTER_BASE_URL
            api_key = ask("  API key: ").strip()
            if not api_key:
                log("no key entered")
                return False
        else:
            chosen = found[idx]

    if chosen is not None:
        model = _choose_model(chosen, ask, log, model) if not (assume_yes and not model) else (model or (chosen.models[0] if chosen.models else ""))
    else:
        model = model or (ask(f"  Model id [{creds.DEFAULT_OPENROUTER_MODEL}]: ").strip() if not assume_yes else "") or creds.DEFAULT_OPENROUTER_MODEL

    updates = env_updates_for(chosen, model, api_key=api_key, base_url=base_url)
    label = chosen.label if chosen else f"API key @ {updates['LLM_BASE_URL']}"

    if not skip_verify:
        log(f"  testing {label} with model {model} ...")
        if not verify({**current, **updates}, log):
            if assume_yes or provider:
                return False
            retry = ask("  Save anyway? [y/N]: ").strip().lower()
            if retry != "y":
                return False

    write_env_values(env_path, updates)
    log(f"  saved to {env_path}: LLM_PROVIDER={updates['LLM_PROVIDER']} LLM_MODEL={model}")
    return True
