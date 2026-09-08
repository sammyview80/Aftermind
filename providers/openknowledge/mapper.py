from datetime import datetime
from typing import Iterable, Mapping, Optional

from domain.models.knowledge_document import KnowledgeDocument, KnowledgeSection
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


def build_document(
    title: str,
    slug: str,
    sections: Mapping[str, Iterable[Memory]],
    scope: Optional[MemoryScope] = None,
) -> KnowledgeDocument:
    """Assemble a KnowledgeDocument from already-selected, consolidated
    memories, grouped by section heading.

    This does NOT decide which memories belong here or rewrite them into
    prose — that consolidation judgment is the Consolidation Engine's
    job (next phase). This is pure structural assembly: given a heading
    -> memories mapping the caller has already curated, produce a
    document. Do not pass every StoredMemory through this — only
    consolidated/durable semantic knowledge belongs in OpenKnowledge.
    """
    doc_sections = []
    source_ids: list[str] = []

    for heading, memories in sections.items():
        memories = list(memories)
        body = " ".join(m.content.rstrip(".") + "." for m in memories)
        doc_sections.append(KnowledgeSection(heading=heading, body=body))
        source_ids.extend(m.memory_id for m in memories)

    return KnowledgeDocument(
        scope=scope,
        slug=slug,
        title=title,
        sections=tuple(doc_sections),
        source_memory_ids=tuple(source_ids),
    )


def document_to_dict(document: KnowledgeDocument) -> dict:
    return {
        "document_id": document.document_id,
        "slug": document.slug,
        "title": document.title,
        "sections": [{"heading": s.heading, "body": s.body} for s in document.sections],
        "source_memory_ids": list(document.source_memory_ids),
        "version": document.version,
        "metadata": dict(document.metadata),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def document_from_dict(data: dict, scope: Optional[MemoryScope] = None) -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=data["document_id"],
        scope=scope,
        slug=data["slug"],
        title=data["title"],
        sections=tuple(KnowledgeSection(**s) for s in data["sections"]),
        source_memory_ids=tuple(data["source_memory_ids"]),
        version=data["version"],
        metadata=data.get("metadata", {}),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
    )
