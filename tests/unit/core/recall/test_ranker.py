from datetime import datetime, timedelta, timezone

from core.recall.ranker import Ranker
from domain.models.memory import Memory


def test_rank_orders_by_relevance_to_search_terms():
    relevant = Memory(content="the login flow uses OAuth for authentication")
    irrelevant = Memory(content="billing invoices are generated monthly")

    ranked = Ranker().rank(("login flow OAuth",), [irrelevant, relevant])

    assert ranked[0] is relevant


def test_rank_breaks_ties_with_confidence():
    now = datetime.now(timezone.utc)
    low_confidence = Memory(content="topic x detail", confidence=0.1, updated_at=now)
    high_confidence = Memory(content="topic x detail", confidence=0.9, updated_at=now)

    ranked = Ranker().rank(("topic x detail",), [low_confidence, high_confidence])

    assert ranked[0] is high_confidence


def test_rank_prefers_more_recent_memory_when_otherwise_equal():
    older = Memory(content="topic x", confidence=0.5, updated_at=datetime.now(timezone.utc) - timedelta(days=5))
    newer = Memory(content="topic x", confidence=0.5, updated_at=datetime.now(timezone.utc))

    ranked = Ranker().rank(("topic x",), [older, newer])

    assert ranked[0] is newer


def test_rank_respects_limit():
    memories = [Memory(content=f"topic {i}") for i in range(5)]
    ranked = Ranker().rank(("topic",), memories, limit=2)
    assert len(ranked) == 2


def test_rank_empty_memories_returns_empty_list():
    assert Ranker().rank(("anything",), []) == []
