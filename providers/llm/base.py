from abc import ABC, abstractmethod
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a system prompt by name (without extension) from
    providers/llm/prompts/<name>.md, e.g. load_prompt("reconciler")."""
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text().strip()


class BaseLLMProvider(ABC):
    """Shared shape for vendor LLM adapters. Satisfies
    domain.interfaces.llm_provider.LLMProvider (structurally, via
    `complete`) so core/* code depends only on that Protocol, never on a
    specific vendor SDK.
    """

    @abstractmethod
    def complete(self, prompt: str) -> str:
        """Send `prompt` to the model and return its raw text response."""
        ...
