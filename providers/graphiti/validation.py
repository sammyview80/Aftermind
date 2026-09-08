from providers.graphiti.mapper import Triple

MAX_ENTITY_LENGTH = 60
MAX_ENTITY_WORDS = 4
MAX_SIMPLE_SENTENCE_WORDS = 12
_COMPOUND_MARKERS = (";", " and ", " but ", " while ", " whereas ")


def is_valid_triple(triple: Triple) -> bool:
    """A triple is only fit for the graph if its endpoints are actual
    entity names, not sentence fragments. Guards against exactly the
    failure mode a greedy regex produces on compound/merged content:
    source/target not empty, short, no clause-joining punctuation, and
    a bounded word count (a real entity name is a noun phrase, not a
    clause)."""
    return (
        bool(triple.relation)
        and _is_sane_entity(triple.source)
        and _is_sane_entity(triple.target)
    )


def _is_sane_entity(name: str) -> bool:
    name = name.strip()
    if not name or len(name) > MAX_ENTITY_LENGTH:
        return False
    if len(name.split()) > MAX_ENTITY_WORDS:
        return False
    if any(marker in name for marker in (";", ",")):
        return False
    return True


def is_simple_sentence(text: str) -> bool:
    """Heuristic for the regex fast path's applicability: one short,
    single-clause sentence. Anything compound (joined clauses, merged
    facts, long content) should go through the structured extractor
    instead of a regex that can't parse structure."""
    text = text.strip()
    if not text or len(text.split()) > MAX_SIMPLE_SENTENCE_WORDS:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in _COMPOUND_MARKERS)
