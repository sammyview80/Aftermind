from typing import Optional

from providers.llm.base import BaseLLMProvider

DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 2048


class AnthropicProvider(BaseLLMProvider):
    """LLMProvider backed by the Anthropic API. The `anthropic` package is
    imported lazily so importing this module never requires it — only
    instantiating this class does."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        client=None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self._client = client
        else:
            try:
                from anthropic import Anthropic
            except ImportError as exc:
                raise ImportError(
                    "AnthropicProvider requires the 'anthropic' package: pip install anthropic"
                ) from exc
            self._client = Anthropic(api_key=api_key)

    def complete(self, prompt: str) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
