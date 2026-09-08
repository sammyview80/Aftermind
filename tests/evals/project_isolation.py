"""Metric 4: project isolation — running many scenarios' worth of
projects through the same Aftermind deployment must never let one
project's facts leak into another's recall."""
from domain.models.recall_query import RecallQuery
from tests.evals.harness import build_service, run_scenario
from tests.evals.scenarios import SCENARIOS


def test_no_scenario_leaks_into_another_scenarios_recall():
    """Run every scenario against one shared service (one shared
    deployment, many projects) and check none of them ever surfaces
    another scenario's subject/value in its own recall context."""
    service = build_service()
    runs = [run_scenario(scenario, service) for scenario in SCENARIOS]

    leaks = []
    for run in runs:
        for other in runs:
            if other is run:
                continue
            if other.scenario.new_value in run.aftermind_context or other.scenario.old_value in run.aftermind_context:
                leaks.append((run.scenario.scenario_id, other.scenario.scenario_id))

    assert leaks == [], f"cross-project leaks: {leaks[:5]}"


def test_different_project_id_same_tenant_is_isolated():
    from core.facade import AftermindService
    from domain.models.experience import Experience
    from domain.models.scope import MemoryScope

    service = build_service()
    scope_a = MemoryScope.of(tenant_id="shared-tenant", project_id="project-a")
    scope_b = MemoryScope.of(tenant_id="shared-tenant", project_id="project-b")

    service.observe(Experience(scope=scope_a, output="Project A's database is CockroachDB, chosen for HA."))
    service.observe(Experience(scope=scope_b, output="Project B's database is DynamoDB, chosen for scale."))

    result_a = service.recall(RecallQuery(scope=scope_a, text="What database does this project use?"))
    result_b = service.recall(RecallQuery(scope=scope_b, text="What database does this project use?"))

    assert "CockroachDB" in result_a.context and "DynamoDB" not in result_a.context
    assert "DynamoDB" in result_b.context and "CockroachDB" not in result_b.context


if __name__ == "__main__":
    service = build_service()
    runs = [run_scenario(scenario, service) for scenario in SCENARIOS]
    leaks = sum(
        1
        for run in runs
        for other in runs
        if other is not run and (other.scenario.new_value in run.aftermind_context)
    )
    print(f"cross-project leaks across {len(runs)} scenarios: {leaks}")
