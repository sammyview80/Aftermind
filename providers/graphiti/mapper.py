import re
from dataclasses import dataclass
from typing import Union

from domain.interfaces.graph_store import GraphStore
from domain.models.candidate import Candidate
from domain.models.memory import Memory

_RELATION_VERBS = (
    "uses",
    "runs on",
    "depends on",
    "built on",
    "built with",
    "powered by",
    "hosted on",
    "owned by",
    "part of",
)

_TRIPLE_PATTERN = re.compile(
    rf"^(?P<source>.+?)\s+(?P<relation>{'|'.join(_RELATION_VERBS)})\s+(?P<target>.+?)[.!]?$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Triple:
    """A source -> relation -> target fact, ready for the graph store."""

    source: str
    relation: str
    target: str


def normalize_relation(text: str) -> str:
    return re.sub(r"\s+", "_", text.strip().upper())


_normalize_relation = normalize_relation  # internal alias, kept for callers within this module


def extract_triples(text: str) -> list[Triple]:
    """Parse a "<source> <relation verb> <target>" fact out of free text,
    e.g. "Aftermind uses PostgreSQL." -> Aftermind -USES-> PostgreSQL.
    Returns [] if the text doesn't match a known relation shape."""
    match = _TRIPLE_PATTERN.match(text.strip())
    if not match:
        return []
    return [
        Triple(
            source=match["source"].strip(),
            relation=_normalize_relation(match["relation"]),
            target=match["target"].strip(),
        )
    ]


def triples_from(item: Union[Candidate, Memory]) -> list[Triple]:
    """Prefer structured `relationships` text already extracted onto the
    candidate/memory; fall back to parsing raw `content` when empty."""
    triples: list[Triple] = []
    for relationship_text in item.relationships:
        triples.extend(extract_triples(relationship_text))
    if not triples:
        triples.extend(extract_triples(item.content))
    return triples


def sync_to_graph(item: Union[Candidate, Memory], graph_store: GraphStore) -> list[Triple]:
    """Extract triples from a candidate/memory and write them into the
    graph store, returning what was written."""
    triples = triples_from(item)
    for triple in triples:
        graph_store.upsert_entity(triple.source, scope=item.scope)
        graph_store.upsert_entity(triple.target, scope=item.scope)
        graph_store.upsert_relationship(triple.source, triple.relation, triple.target, scope=item.scope)
    return triples
