from core.consolidation.planner import ConsolidationPlanner
from core.consolidation.triggers import ConsolidationTrigger
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


def test_plan_clusters_related_memories_above_min_group_size():
    memories = [
        Memory(content="Client rejected bright blue."),
        Memory(content="Client prefers dark layouts."),
        Memory(content="Client approved black and gold."),
    ]

    plans = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.TOPIC_THRESHOLD)

    assert len(plans) == 1
    assert len(plans[0].memories) == 3
    assert plans[0].trigger == ConsolidationTrigger.TOPIC_THRESHOLD


def test_plan_drops_clusters_below_min_group_size():
    memories = [
        Memory(content="Client prefers dark layouts."),
        Memory(content="Unrelated fact about billing invoices."),
    ]

    plans = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.MANUAL)

    assert plans == []


def test_plan_separates_unrelated_topics_into_different_clusters():
    memories = [
        Memory(content="Client prefers dark layouts."),
        Memory(content="Client approved black and gold."),
        Memory(content="Client rejected bright blue."),
        Memory(content="Team uses PostgreSQL for storage."),
        Memory(content="Team uses Neo4j for the graph."),
        Memory(content="Team prefers PostgreSQL over MongoDB."),
    ]

    plans = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.TOPIC_THRESHOLD)

    assert len(plans) == 2
    contents_by_plan = [{m.content for m in p.memories} for p in plans]
    assert {"Client prefers dark layouts.", "Client approved black and gold.", "Client rejected bright blue."} in contents_by_plan


def test_plan_carries_scope_through():
    scope = MemoryScope.of(tenant_id="t1")
    memories = [Memory(scope=scope, content=f"Client prefers option {i}") for i in range(3)]

    plans = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.MANUAL, scope=scope)

    assert plans[0].scope is scope
