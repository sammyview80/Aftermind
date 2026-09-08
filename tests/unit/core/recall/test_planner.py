from core.recall.planner import RecallPlanner
from domain.enums.memory_type import MemoryType
from domain.models.checkpoint import Checkpoint
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope


def test_plan_without_checkpoint_uses_query_text_only():
    query = RecallQuery(text="Continue Aftermind")
    plan = RecallPlanner().plan(query, checkpoint=None)

    assert plan.search_terms == ("Continue Aftermind",)
    assert plan.fetch_checkpoint is True
    assert plan.memory_types == (MemoryType.EPISODIC, MemoryType.SEMANTIC)


def test_plan_prioritizes_checkpoint_content_before_query_text():
    checkpoint = Checkpoint(
        goal="Build the login flow",
        current="wiring up session handling",
        blockers=["waiting on OAuth client secret"],
        next_steps=["add tests"],
    )
    query = RecallQuery(text="Continue Aftermind")

    plan = RecallPlanner().plan(query, checkpoint)

    assert plan.search_terms[0] == "Build the login flow"
    assert "wiring up session handling" in plan.search_terms
    assert "waiting on OAuth client secret" in plan.search_terms
    assert "add tests" in plan.search_terms
    assert plan.search_terms[-1] == "Continue Aftermind"


def test_plan_derives_entity_seeds_from_checkpoint_and_query():
    checkpoint = Checkpoint(goal="Build the login flow using OAuth")
    query = RecallQuery(text="Continue Aftermind")

    plan = RecallPlanner().plan(query, checkpoint)

    assert "login" in plan.entity_seeds
    assert "oauth" in plan.entity_seeds
    assert "aftermind" in plan.entity_seeds
    assert "the" not in plan.entity_seeds  # stopword filtered


def test_plan_respects_explicit_memory_types_and_scope_and_limit():
    scope = MemoryScope.of(tenant_id="t1")
    query = RecallQuery(scope=scope, memory_types=[MemoryType.PROCEDURAL], limit=3)

    plan = RecallPlanner().plan(query, checkpoint=None)

    assert plan.scope is scope
    assert plan.memory_types == (MemoryType.PROCEDURAL,)
    assert plan.limit == 3


def test_plan_deduplicates_search_terms():
    checkpoint = Checkpoint(goal="Continue Aftermind")
    query = RecallQuery(text="Continue Aftermind")

    plan = RecallPlanner().plan(query, checkpoint)

    assert plan.search_terms == ("Continue Aftermind",)
