import json
import urllib.request
from typing import Optional

from providers.llm.base import BaseLLMProvider
from providers.llm.config import get_llm_config

DEFAULT_TIMEOUT = 60


class OpenRouterProvider(BaseLLMProvider):
    """Generic OpenAI-compatible chat-completions provider. Defaults to
    OpenRouter (LLM_BASE_URL) but works against any compatible endpoint —
    another vendor's gateway, a self-hosted one — since nothing here is
    hardcoded to a specific model family. Model/key/base_url come from
    LLM_MODEL/LLM_API_KEY/LLM_BASE_URL (env or .env) unless overridden.
    Uses only the standard library, no vendor SDK required.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        opener=urllib.request.urlopen,
    ) -> None:
        config = get_llm_config()
        self.model = model or config.model
        self.api_key = api_key or config.api_key
        self.base_url = (base_url or config.base_url).rstrip("/")
        self.timeout = timeout
        self._opener = opener

        if not self.api_key:
            raise ValueError("No LLM API key configured (set LLM_API_KEY in the environment or .env)")
        if not self.model:
            raise ValueError("No LLM model configured (set LLM_MODEL in the environment or .env)")

    def complete(self, prompt: str) -> str:
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}]}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with self._opener(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        return payload["choices"][0]["message"]["content"] or ""
