"""Metric: checkpoint recovery success — after session 3's checkpoint,
does a brand-new session recover the right goal/next-step, not a stale
or missing one."""
from core.facade import AftermindService
from domain.models.experience import Experience
from domain.models.scope import MemoryScope
from tests.evals.harness import build_service, run_all
from tests.evals.metrics import compute_report
from tests.evals.scenarios import SCENARIOS


def test_checkpoint_recovery_rate_is_high():
    report = compute_report(run_all(SCENARIOS))
    assert report.checkpoint_recovery_rate >= 0.9, report.summary()


def test_checkpoint_survives_across_a_new_session_scope():
    scenario = SCENARIOS[2]
    service = build_service()
    scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id)

    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))
        if session.checkpoint:
            service.checkpoint(
                scope=scope, goal=session.checkpoint_goal, current=session.checkpoint_current,
                next_steps=session.checkpoint_next_steps,
            )

    new_session_scope = MemoryScope.of(tenant_id="eval", project_id=scenario.scenario_id, session_id="s2")
    checkpoint = service.latest_checkpoint(new_session_scope)

    assert checkpoint is not None
    assert scenario.new_value in checkpoint.goal
    assert checkpoint.next_steps  # carried the "what's left" forward, not just the goal


def test_checkpoint_is_not_found_for_a_project_that_never_checkpointed():
    service = build_service()
    scope = MemoryScope.of(tenant_id="eval", project_id="never-checkpointed")
    assert service.latest_checkpoint(scope) is None


if __name__ == "__main__":
    report = compute_report(run_all(SCENARIOS))
    print(report.summary())
