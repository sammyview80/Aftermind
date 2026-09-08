"""Metric 1: recall accuracy — of what gets recalled, how much of it is
actually useful (memory precision), and of what should have been
recalled, how much actually surfaced (memory recall)."""
from tests.evals.harness import run_all
from tests.evals.metrics import compute_report
from tests.evals.scenarios import SCENARIOS


def test_memory_precision_is_high():
    """Useful recalled memories / total recalled memories — the
    milestone's headline ratio. Every retrieved memory in these
    single-topic scopes should be on-topic; near-1.0 is expected."""
    report = compute_report(run_all(SCENARIOS))
    assert report.memory_precision >= 0.9, report.summary()


def test_memory_recall_is_high():
    """Of the facts a correct answer needs, how many actually made it
    into the recalled context."""
    report = compute_report(run_all(SCENARIOS))
    assert report.memory_recall >= 0.9, report.summary()


if __name__ == "__main__":
    report = compute_report(run_all(SCENARIOS))
    print(report.summary())
