from typing import Any, Iterable, Optional

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 30.0


class AftermindClient:
    """Python SDK for Aftermind's REST API — the same four operations as
    the MCP tools and the core facade: observe, recall, checkpoint,
    search. Talks HTTP (via httpx), no direct dependency on Aftermind's
    internals, so it works from any process/language boundary the REST
    API is reachable from.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = http_client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "AftermindClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(f"{self.base_url}{path}", json=json)
        response.raise_for_status()
        return response.json()

    def observe(
        self,
        scope: dict[str, str],
        input: str = "",
        output: str = "",
        event_type: str = "agent_message",
    ) -> dict[str, Any]:
        """Learn from one turn of agent experience. Returns
        {"created": bool, "memory_id"?: str, "content"?: str}."""
        return self._post(
            "/observe",
            {"scope": {"levels": scope}, "input": input, "output": output, "event_type": event_type},
        )

    def recall(self, scope: dict[str, str], text: str = "", limit: int = 10) -> dict[str, Any]:
        """Reconstruct context (checkpoint + relevant memories) for a
        request. Returns {"context": str, "memories": [...], "related_entities": [...]}."""
        return self._post("/recall", {"scope": {"levels": scope}, "text": text, "limit": limit})

    def checkpoint(
        self,
        scope: dict[str, str],
        goal: str = "",
        current: str = "",
        completed: Iterable[str] = (),
        blockers: Iterable[str] = (),
        next_steps: Iterable[str] = (),
        memory_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Explicitly record a checkpoint of where the agent's work stands."""
        return self._post(
            "/checkpoint",
            {
                "scope": {"levels": scope},
                "goal": goal,
                "current": current,
                "completed": list(completed),
                "blockers": list(blockers),
                "next_steps": list(next_steps),
                "memory_ids": list(memory_ids),
            },
        )

    def latest_checkpoint(self, scope: dict[str, str]) -> dict[str, Any]:
        return self._post("/checkpoint/latest", {"scope": {"levels": scope}})

    def search(self, scope: dict[str, str], query: str, limit: int = 5) -> dict[str, Any]:
        """Direct memory search, no checkpoint or context compression."""
        return self._post("/search", {"scope": {"levels": scope}, "query": query, "limit": limit})
