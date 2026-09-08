"""Milestone 7 acceptance test: run the full scripted multi-session
scenario suite (30 topics >= the milestone's 20-50 target) and show
Hermes + Aftermind performs materially better than Hermes alone.

Run standalone for the human-readable report:
    .venv/bin/python -m tests.evals.test_benchmark_suite
"""
from tests.evals.harness import run_all
from tests.evals.metrics import compute_report
from tests.evals.scenarios import SCENARIOS


def test_suite_covers_at_least_twenty_scenarios():
    assert len(SCENARIOS) >= 20


def test_aftermind_performs_materially_better_than_baseline():
    report = compute_report(run_all(SCENARIOS))

    # Baseline is a fresh Hermes session with no memory system — it has
    # no way to answer a cross-session question by construction, so its
    # success rate should sit at (or near) zero.
    assert report.baseline_success_rate <= 0.1, report.summary()
    assert report.aftermind_success_rate >= 0.9, report.summary()
    assert report.aftermind_success_rate - report.baseline_success_rate >= 0.8, report.summary()


def test_memory_hygiene_metrics_meet_bar():
    report = compute_report(run_all(SCENARIOS))

    assert report.memory_precision >= 0.85, report.summary()
    assert report.memory_recall >= 0.9, report.summary()
    assert report.stale_memory_rate <= 0.05, report.summary()
    assert report.duplicate_memory_rate <= 0.1, report.summary()
    assert report.checkpoint_recovery_rate >= 0.9, report.summary()


def test_context_and_latency_budget_meet_bar():
    report = compute_report(run_all(SCENARIOS))

    assert report.avg_injected_tokens <= 150, report.summary()
    assert report.avg_recall_latency_ms <= 50.0, report.summary()


if __name__ == "__main__":
    report = compute_report(run_all(SCENARIOS))
    print(f"Milestone 7 benchmark — {len(SCENARIOS)} scripted multi-session scenarios\n")
    print(report.summary())
