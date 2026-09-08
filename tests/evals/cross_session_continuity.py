"""Metric 2: cross-session continuity — session 4 asks "what were we
working on and what changed", after the decision from session 1 was
overturned in session 2 and implementation continued in session 3.
"""
from core.facade import AftermindService
from domain.models.experience import Experience
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from tests.evals.harness import build_service, run_scenario
from tests.evals.scenarios import SCENARIOS


def test_baseline_has_no_cross_session_memory_by_construction():
    """A fresh Hermes session with no memory system carries nothing
    forward — this is the honest definition of "without Aftermind" for
    a stateless-per-session CLI, and the reason the baseline arm can't
    pass any cross-session question."""
    run = run_scenario(SCENARIOS[0], build_service())
    assert run.baseline_context == ""


def test_aftermind_continues_the_task_across_sessions():
    run = run_scenario(SCENARIOS[0], build_service())

    assert run.scenario.new_value in run.aftermind_context
    assert "## Where you left off" in run.aftermind_context  # session 3's checkpoint carried forward
    assert run.scenario.aspect in run.aftermind_context.lower() or run.scenario.aspect in run.checkpoint_goal.lower()


def test_a_brand_new_session_id_still_finds_prior_context():
    """Scope stabilization (session_id stripped) is what makes this
    work — a literally different Hermes session_id must still resolve
    to the same durable memory/checkpoint."""
    scenario = SCENARIOS[1]
    service = build_service()
    scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id)

    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))
        if session.checkpoint:
            service.checkpoint(
                scope=scope, goal=session.checkpoint_goal, current=session.checkpoint_current,
                next_steps=session.checkpoint_next_steps,
            )

    fresh_session_scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id, session_id="brand-new-session")
    result = service.recall(RecallQuery(scope=fresh_session_scope, text=scenario.query))

    assert scenario.new_value in result.context


if __name__ == "__main__":
    run = run_scenario(SCENARIOS[0], build_service())
    print("baseline context:", repr(run.baseline_context))
    print("aftermind context:\n", run.aftermind_context)
