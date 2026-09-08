"""Build the configured LLMProvider from environment/.env.

    LLM_PROVIDER=openai_compatible   (default) LLM_BASE_URL + LLM_API_KEY + LLM_MODEL
    LLM_PROVIDER=codex_oauth         reuse the Codex CLI's ChatGPT login; LLM_MODEL
    LLM_PROVIDER=claude_code_oauth   reuse the Claude Code login; LLM_MODEL
"""
import os

from domain.interfaces.llm_provider import LLMProvider
from providers.llm.credentials import CLAUDE_CODE_OAUTH, CODEX_OAUTH, OPENAI_COMPATIBLE

PROVIDERS = (OPENAI_COMPATIBLE, CODEX_OAUTH, CLAUDE_CODE_OAUTH)


def llm_provider_id(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    value = (env.get("LLM_PROVIDER") or OPENAI_COMPATIBLE).strip().lower()
    if value not in PROVIDERS:
        raise ValueError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)}, got {value!r}")
    return value


def build_llm_provider(env: dict | None = None) -> LLMProvider:
    env = os.environ if env is None else env
    provider = llm_provider_id(env)
    model = (env.get("LLM_MODEL") or "").strip()

    if provider == CODEX_OAUTH:
        from providers.llm.codex_oauth import DEFAULT_MODEL, CodexOAuthProvider

        return CodexOAuthProvider(model=model or DEFAULT_MODEL)

    if provider == CLAUDE_CODE_OAUTH:
        from providers.llm.claude_code_oauth import DEFAULT_MODEL, ClaudeCodeOAuthProvider

        return ClaudeCodeOAuthProvider(model=model or DEFAULT_MODEL, access_token=env.get("CLAUDE_CODE_OAUTH_TOKEN") or None)

    from providers.llm.openrouter import OpenRouterProvider

    return OpenRouterProvider()


def llm_configured(env: dict | None = None) -> bool:
    """Whether observe()/consolidation can call a model with the current env."""
    env = os.environ if env is None else env
    try:
        provider = llm_provider_id(env)
    except ValueError:
        return False
    if provider == OPENAI_COMPATIBLE:
        return bool(env.get("LLM_API_KEY") and env.get("LLM_MODEL"))
    return True  # OAuth providers resolve tokens at call time
