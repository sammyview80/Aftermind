from typing import Protocol


class LLMProvider(Protocol):
    """A text-completion backend. Reconciliation prompts are plain text in,
    plain text out — providers/llm/* adapt this to a specific vendor SDK;
    tests can swap in a deterministic fake."""

    def complete(self, prompt: str) -> str: ...
