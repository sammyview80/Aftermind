from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from domain.models.knowledge_document import KnowledgeDocument
from domain.models.scope import MemoryScope
from providers.openknowledge.client import LocalMarkdownClient
from providers.openknowledge.mapper import document_from_dict, document_to_dict


def _scope_key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


class OpenKnowledgeStore:
    """DocumentStore implementation backed by LocalMarkdownClient (or any
    client exposing the same read/write/search shape). Versions
    documents by slug+scope, same pattern as CheckpointManager."""

    def __init__(self, client: LocalMarkdownClient) -> None:
        self._client = client

    def get(self, slug: str, scope: Optional[MemoryScope] = None) -> Optional[KnowledgeDocument]:
        data = self._client.read(slug, scope_key=_scope_key(scope))
        return document_from_dict(data, scope=scope) if data else None

    def save(self, document: KnowledgeDocument) -> KnowledgeDocument:
        scope_key = _scope_key(document.scope)
        existing = self._client.read(document.slug, scope_key=scope_key)

        to_save = replace(
            document,
            version=(existing["version"] + 1) if existing else 1,
            created_at=datetime.fromisoformat(existing["created_at"]) if existing else document.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        self._client.write(
            slug=to_save.slug,
            scope_key=scope_key,
            data=document_to_dict(to_save),
            markdown=to_save.to_markdown(),
        )
        return to_save

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[KnowledgeDocument]:
        results = self._client.search(query, scope_key=_scope_key(scope), limit=limit)
        return [document_from_dict(data, scope=scope) for data in results]
