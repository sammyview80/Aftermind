"""Metric 5: context efficiency — recall must hand back a compact,
bounded package, not a growing dump of raw history, and must not add
meaningful latency to a turn."""
from tests.evals.harness import run_all
from tests.evals.metrics import compute_report
from tests.evals.scenarios import SCENARIOS

MAX_AVG_INJECTED_TOKENS = 150
MAX_AVG_RECALL_LATENCY_MS = 50.0


def test_injected_context_stays_compact():
    report = compute_report(run_all(SCENARIOS))
    assert report.avg_injected_tokens <= MAX_AVG_INJECTED_TOKENS, report.summary()


def test_injected_context_compresses_as_history_accumulates():
    """One 3-sentence topic in isolation doesn't show compression —
    ContextBuilder's headers/sections are naturally comparable in size
    to 2-3 short sentences. The real efficiency claim is about NOT
    growing unboundedly as a project accumulates months of history:
    replay many topics into one shared scope and confirm recall's
    context stays flat/bounded instead of scaling with the full raw
    transcript."""
    from core.facade import AftermindService
    from domain.models.experience import Experience
    from domain.models.recall_query import RecallQuery
    from domain.models.scope import MemoryScope
    from tests.evals.harness import build_service

    service = build_service()
    scope = MemoryScope.of(tenant_id="eval", project_id="accumulated-project")

    topics = SCENARIOS[:10]
    raw_transcript_words = 0
    for scenario in topics:
        for session in scenario.sessions:
            service.observe(Experience(scope=scope, output=session.statement))
            raw_transcript_words += len(session.statement.split())

    last_topic = topics[-1]
    result = service.recall(RecallQuery(scope=scope, text=last_topic.query))
    injected_words = len(result.context.split())

    assert injected_words < raw_transcript_words * 0.5


def test_recall_latency_is_low():
    report = compute_report(run_all(SCENARIOS))
    assert report.avg_recall_latency_ms <= MAX_AVG_RECALL_LATENCY_MS, report.summary()


if __name__ == "__main__":
    report = compute_report(run_all(SCENARIOS))
    print(report.summary())
