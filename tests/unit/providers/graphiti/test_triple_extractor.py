import json

from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.graphiti.mapper import Triple
from providers.graphiti.triple_extractor import LLMTripleExtractor, extract_validated_triples, sync_to_graph


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeGraphStore:
    def __init__(self) -> None:
        self.relationships: list[tuple] = []

    def upsert_entity(self, name, scope=None) -> None:
        pass

    def upsert_relationship(self, source, relation, target, scope=None) -> None:
        self.relationships.append((source, relation, target))

    def find_related(self, entity, scope=None, limit=5) -> list[str]:
        return []


def test_llm_extractor_maps_response_to_triples():
    response = json.dumps(
        [
            {"source": "Aftermind", "relation": "uses", "target": "SQLite"},
            {"source": "Aftermind", "relation": "uses", "target": "Graphiti"},
        ]
    )
    extractor = LLMTripleExtractor(ScriptedLLM(response))

    triples = extractor.extract("Aftermind stores memories in SQLite and entities in Graphiti")

    assert triples == [Triple("Aftermind", "USES", "SQLite"), Triple("Aftermind", "USES", "Graphiti")]


def test_llm_extractor_filters_out_invalid_triples():
    response = json.dumps(
        [
            {"source": "Aftermind", "relation": "uses", "target": "SQLite"},
            {"source": "", "relation": "uses", "target": "Graphiti"},  # empty source, dropped
        ]
    )
    extractor = LLMTripleExtractor(ScriptedLLM(response))

    triples = extractor.extract("some content")

    assert triples == [Triple("Aftermind", "USES", "SQLite")]


def test_build_prompt_prefixes_system_prompt():
    extractor = LLMTripleExtractor(ScriptedLLM("[]"), system_prompt="# Aftermind Graph Triple Extractor")
    assert extractor.build_prompt("x").startswith("# Aftermind Graph Triple Extractor")


def test_extract_validated_triples_uses_regex_fast_path_for_simple_content():
    memory = Memory(content="Aftermind uses PostgreSQL.")
    llm = ScriptedLLM("[]")
    extractor = LLMTripleExtractor(llm)

    triples = extract_validated_triples(memory, llm_extractor=extractor)

    assert triples == [Triple("Aftermind", "USES", "PostgreSQL")]
    assert llm.prompts == []  # regex path succeeded — LLM never called


def test_extract_validated_triples_falls_back_to_llm_for_compound_content():
    memory = Memory(content="Aftermind stores memories in SQLite and entities in Graphiti; Aftermind uses SQLite")
    response = json.dumps(
        [
            {"source": "Aftermind", "relation": "uses", "target": "SQLite"},
            {"source": "Aftermind", "relation": "uses", "target": "Graphiti"},
        ]
    )
    extractor = LLMTripleExtractor(ScriptedLLM(response))

    triples = extract_validated_triples(memory, llm_extractor=extractor)

    assert triples == [Triple("Aftermind", "USES", "SQLite"), Triple("Aftermind", "USES", "Graphiti")]


def test_extract_validated_triples_returns_empty_without_llm_extractor_for_compound_content():
    memory = Memory(content="Aftermind stores memories in SQLite and entities in Graphiti; Aftermind uses SQLite")
    assert extract_validated_triples(memory, llm_extractor=None) == []


def test_sync_to_graph_writes_only_validated_triples():
    scope = MemoryScope.of(tenant_id="t1")
    memory = Memory(scope=scope, content="Aftermind stores memories in SQLite and entities in Graphiti; Aftermind uses SQLite")
    response = json.dumps(
        [
            {"source": "Aftermind", "relation": "uses", "target": "SQLite"},
            {"source": "Aftermind", "relation": "uses", "target": "Graphiti"},
        ]
    )
    graph_store = FakeGraphStore()
    extractor = LLMTripleExtractor(ScriptedLLM(response))

    written = sync_to_graph(memory, graph_store, llm_extractor=extractor)

    assert written == [Triple("Aftermind", "USES", "SQLite"), Triple("Aftermind", "USES", "Graphiti")]
    assert ("Aftermind", "USES", "SQLite") in graph_store.relationships
    assert ("Aftermind", "USES", "Graphiti") in graph_store.relationships
    # never the garbled sentence-sized entity name the old regex produced
    assert not any("stores memories" in rel[0] for rel in graph_store.relationships)
