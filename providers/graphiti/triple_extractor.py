from typing import Optional, Union

from core.json_utils import parse_json_response
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.llm_provider import LLMProvider
from domain.models.candidate import Candidate
from domain.models.memory import Memory
from providers.graphiti.mapper import Triple, extract_triples, normalize_relation
from providers.graphiti.validation import is_simple_sentence, is_valid_triple

_PROMPT_TEMPLATE = """CONTENT:
{content}

Return a JSON array of triples:
[{{"source": "...", "relation": "...", "target": "..."}}]

Respond with ONLY that JSON array — no prose, no markdown code fences.
"""


class LLMTripleExtractor:
    """Structured triple extraction for compound/complex content a
    regex can't safely parse — e.g. a merged memory like "Aftermind
    stores memories in SQLite and entities in Graphiti; Aftermind uses
    SQLite" should become two clean triples, not one triple with a
    sentence-sized entity name.

    Every triple returned is validated (is_valid_triple) before it
    reaches the caller — an LLM can still hallucinate a bad shape, and
    this is the one place responsible for not letting that through.
    """

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, content: str) -> str:
        task = _PROMPT_TEMPLATE.format(content=content)
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def extract(self, content: str) -> list[Triple]:
        raw = self._llm.complete(self.build_prompt(content))
        proposals = parse_json_response(raw)

        # A real model can drift from "JSON array" (e.g. {"triples": [...]}
        # or a single object) despite the prompt — degrade to empty rather
        # than let a malformed shape crash the pipeline.
        if isinstance(proposals, dict):
            proposals = proposals.get("triples", [])
        if not isinstance(proposals, list):
            return []

        triples = [
            Triple(
                source=str(p.get("source", "")).strip(),
                relation=normalize_relation(str(p.get("relation", ""))),
                target=str(p.get("target", "")).strip(),
            )
            for p in proposals
            if isinstance(p, dict)
        ]
        return [t for t in triples if is_valid_triple(t)]


def extract_validated_triples(
    item: Union[Candidate, Memory], llm_extractor: Optional[LLMTripleExtractor] = None
) -> list[Triple]:
    """The real graph-extraction stage: cheap regex fast path for
    simple atomic sentences, structured LLM extraction for compound/
    merged/complex content — never a regex stretched to cover both.
    Every returned triple passes is_valid_triple(); nothing else does.
    """
    candidates: list[Triple] = []
    for relationship_text in item.relationships:
        if is_simple_sentence(relationship_text):
            candidates.extend(extract_triples(relationship_text))

    if not candidates and is_simple_sentence(item.content):
        candidates.extend(extract_triples(item.content))

    valid = [t for t in candidates if is_valid_triple(t)]
    if valid:
        return valid

    if llm_extractor is None:
        return []

    source_text = " ".join(item.relationships) if item.relationships else item.content
    return llm_extractor.extract(source_text)


def sync_to_graph(
    item: Union[Candidate, Memory],
    graph_store: GraphStore,
    llm_extractor: Optional[LLMTripleExtractor] = None,
) -> list[Triple]:
    """Extract validated triples from a candidate/memory and write them
    into the graph store, returning what was written. This is the
    write path AftermindService.observe() actually uses — see
    providers/graphiti/mapper.sync_to_graph for the older regex-only
    version (still exercised directly by its own tests, but no longer
    the one wired into the live pipeline)."""
    triples = extract_validated_triples(item, llm_extractor)
    for triple in triples:
        graph_store.upsert_entity(triple.source, scope=item.scope)
        graph_store.upsert_entity(triple.target, scope=item.scope)
        graph_store.upsert_relationship(triple.source, triple.relation, triple.target, scope=item.scope)
    return triples


def mark_stale_in_graph(
    memory: Memory,
    graph_store: GraphStore,
    llm_extractor: Optional[LLMTripleExtractor] = None,
) -> list[Triple]:
    """The supersede-time counterpart to sync_to_graph: re-derive the
    triples a now-superseded memory would have written, and mark each
    as historical rather than deleting it — "Billing -[USES]-> Redis"
    stays queryable for "what did billing use before?" even after
    "Billing -[USES]-> RabbitMQ" becomes the current relationship.
    Best-effort: a store without mark_historical (an older fake in a
    test) is simply skipped, not an error."""
    triples = extract_validated_triples(memory, llm_extractor)
    mark_historical = getattr(graph_store, "mark_historical", None)
    if mark_historical is None:
        return triples
    for triple in triples:
        mark_historical(triple.source, triple.relation, triple.target, scope=memory.scope)
    return triples
