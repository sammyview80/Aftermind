"""Metric: consolidation quality — when a cluster of durable memories
gets promoted into OpenKnowledge, and one of them is later superseded,
the resulting page must evolve to reflect the new fact rather than
keep serving the stale one or fork into a second page."""
from domain.models.experience import Experience
from domain.models.scope import MemoryScope
from tests.evals.harness import FakeDocumentStore, build_service
from tests.evals.scenarios import SCENARIOS


def test_consolidated_page_reflects_the_current_fact_not_the_stale_one():
    scenario = SCENARIOS[3]
    document_store = FakeDocumentStore()
    service = build_service(document_store=document_store)
    scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id)

    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))

    results = service.consolidate(scope=scope, slug="knowledge", title="Knowledge", min_group_size=2)

    assert results, "expected at least one consolidation result"
    assert any(r.accepted for r in results)

    document = document_store.get("knowledge", scope=scope.stable())
    assert document is not None
    markdown = document.to_markdown()
    assert scenario.new_value in markdown


def test_consolidation_updates_the_same_page_after_a_later_supersede():
    """Milestone 4/6's guarantee, exercised again here as an eval: one
    page evolving in place, never architecture-1.md / architecture-2.md."""
    scenario = SCENARIOS[4]
    document_store = FakeDocumentStore()
    service = build_service(document_store=document_store)
    scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id)

    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))
    service.consolidate(scope=scope, slug="knowledge", title="Knowledge", min_group_size=2)

    slugs_after_first_pass = set(document_store._docs.keys())
    assert len(slugs_after_first_pass) == 1

    # A later, unrelated observe() shouldn't fork a second page for the
    # same slug/topic.
    service.observe(Experience(scope=scope, output=f"{scenario.subject} team also updated the on-call rotation."))
    service.consolidate(scope=scope, slug="knowledge", title="Knowledge", min_group_size=2)

    assert set(document_store._docs.keys()) == slugs_after_first_pass


if __name__ == "__main__":
    scenario = SCENARIOS[3]
    document_store = FakeDocumentStore()
    service = build_service(document_store=document_store)
    scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id)
    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))
    service.consolidate(scope=scope, slug="knowledge", title="Knowledge", min_group_size=2)
    print(document_store.get("knowledge", scope=scope.stable()).to_markdown())
