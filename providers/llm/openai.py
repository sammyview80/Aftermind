from typing import Optional

from providers.llm.base import BaseLLMProvider

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(BaseLLMProvider):
    """LLMProvider backed by the OpenAI API. The `openai` package is
    imported lazily so importing this module never requires it — only
    instantiating this class does."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: Optional[str] = None, client=None) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "OpenAIProvider requires the 'openai' package: pip install openai"
                ) from exc
            self._client = OpenAI(api_key=api_key)

    def complete(self, prompt: str) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content or ""
