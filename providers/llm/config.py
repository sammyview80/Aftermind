import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # .env only loaded if python-dotenv is installed; plain env vars still work


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str


def get_llm_config() -> LLMConfig:
    """Read LLM_API_KEY/LLM_MODEL/LLM_BASE_URL from the environment
    (populated from .env by load_dotenv() above). Read fresh each call
    so tests can monkeypatch os.environ without re-importing this module."""
    return LLMConfig(
        api_key=os.environ.get("LLM_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", ""),
        base_url=os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
    )
