from providers.graphiti.mapper import Triple
from providers.graphiti.validation import is_simple_sentence, is_valid_triple


def test_valid_triple_passes():
    assert is_valid_triple(Triple("Aftermind", "USES", "PostgreSQL")) is True


def test_empty_source_or_target_is_invalid():
    assert is_valid_triple(Triple("", "USES", "PostgreSQL")) is False
    assert is_valid_triple(Triple("Aftermind", "USES", "")) is False


def test_empty_relation_is_invalid():
    assert is_valid_triple(Triple("Aftermind", "", "PostgreSQL")) is False


def test_sentence_sized_entity_is_invalid():
    # exactly the garbage the greedy regex produced on merged content
    garbage = Triple(
        "Aftermind stores memories in SQLite and entities in Graphiti; Aftermind",
        "USES",
        "SQLite",
    )
    assert is_valid_triple(garbage) is False


def test_entity_with_semicolon_or_comma_is_invalid():
    assert is_valid_triple(Triple("Aftermind; Team", "USES", "SQLite")) is False
    assert is_valid_triple(Triple("Aftermind", "USES", "SQLite, Redis")) is False


def test_overly_long_entity_is_invalid():
    long_name = "A" * 61
    assert is_valid_triple(Triple(long_name, "USES", "SQLite")) is False


def test_is_simple_sentence_accepts_short_atomic_sentence():
    assert is_simple_sentence("Aftermind uses PostgreSQL.") is True


def test_is_simple_sentence_rejects_compound_content():
    assert is_simple_sentence("Aftermind uses SQLite and Graphiti uses Neo4j") is False
    assert is_simple_sentence("Aftermind uses SQLite; Aftermind uses Graphiti") is False


def test_is_simple_sentence_rejects_overly_long_content():
    long_sentence = " ".join(["word"] * 20)
    assert is_simple_sentence(long_sentence) is False


def test_is_simple_sentence_rejects_empty():
    assert is_simple_sentence("") is False
    assert is_simple_sentence("   ") is False
