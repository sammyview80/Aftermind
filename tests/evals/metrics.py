"""Aggregate metrics over a list of harness.ScenarioRun results."""
import re
from dataclasses import dataclass
from itertools import combinations
from statistics import mean

from tests.evals.harness import ScenarioRun, _overlap


def _section(context: str, heading: str) -> str:
    """The body text of one '## Heading' section, up to the next '## '
    or end of string — so a stale-fact check can look specifically at
    "Current facts" without being confused by the same fact legitimately
    appearing (tagged superseded) under "Recent history"."""
    match = re.search(rf"## {re.escape(heading)}\n(.*?)(?=\n## |\Z)", context, re.DOTALL)
    return match.group(1) if match else ""


def _task_succeeded(context: str, expected_contains: tuple[str, ...], stale_statement: str) -> bool:
    if not context:
        return False
    if not all(fact in context for fact in expected_contains):
        return False
    return not _has_stale_leak(context, stale_statement)


def _has_stale_leak(context: str, stale_statement: str) -> bool:
    """True if the *original superseded statement itself* still shows up
    as a live current fact — not just its value word, since a correct
    current memory legitimately says "changed from Redis to RabbitMQ"
    and that shouldn't be penalized as a stale leak."""
    current_section = _section(context, "Current facts")
    return stale_statement in current_section


@dataclass
class BenchmarkReport:
    n_scenarios: int
    baseline_success_rate: float
    aftermind_success_rate: float
    memory_precision: float
    memory_recall: float
    stale_memory_rate: float
    duplicate_memory_rate: float
    checkpoint_recovery_rate: float
    avg_injected_tokens: float
    avg_recall_latency_ms: float
    p95_recall_latency_ms: float

    def summary(self) -> str:
        lines = [
            f"scenarios run:              {self.n_scenarios}",
            f"baseline success rate:      {self.baseline_success_rate:.0%}  (Hermes, no memory system)",
            f"aftermind success rate:     {self.aftermind_success_rate:.0%}  (Hermes + Aftermind)",
            f"memory precision:           {self.memory_precision:.0%}  (useful recalled / total recalled)",
            f"memory recall:              {self.memory_recall:.0%}  (expected facts actually surfaced)",
            f"stale memory rate:          {self.stale_memory_rate:.0%}  (superseded fact leaked as current)",
            f"duplicate memory rate:      {self.duplicate_memory_rate:.0%}  (near-duplicate live memories)",
            f"checkpoint recovery rate:   {self.checkpoint_recovery_rate:.0%}",
            f"avg injected tokens:        {self.avg_injected_tokens:.1f}",
            f"avg recall latency:         {self.avg_recall_latency_ms:.2f} ms",
            f"p95 recall latency:         {self.p95_recall_latency_ms:.2f} ms",
        ]
        return "\n".join(lines)


def _duplicate_rate(contents: list[str]) -> float:
    if len(contents) < 2:
        return 0.0
    pairs = list(combinations(contents, 2))
    duplicates = sum(1 for a, b in pairs if _overlap(a, b) > 0.6)
    return duplicates / len(pairs)


def compute_report(runs: list[ScenarioRun]) -> BenchmarkReport:
    n = len(runs)

    baseline_successes = sum(
        _task_succeeded(r.baseline_context, r.scenario.expected_contains, r.scenario.sessions[0].statement)
        for r in runs
    )
    aftermind_successes = sum(
        _task_succeeded(r.aftermind_context, r.scenario.expected_contains, r.scenario.sessions[0].statement)
        for r in runs
    )

    total_retrieved = sum(len(r.retrieved_memories) for r in runs)
    useful_retrieved = sum(
        sum(1 for content in r.retrieved_memories if r.scenario.new_value in content) for r in runs
    )
    memory_precision = (useful_retrieved / total_retrieved) if total_retrieved else 0.0

    expected_found = sum(1 for r in runs if r.scenario.new_value in r.aftermind_context)
    memory_recall = expected_found / n if n else 0.0

    stale_leaks = sum(_has_stale_leak(r.aftermind_context, r.scenario.sessions[0].statement) for r in runs)
    stale_rate = stale_leaks / n if n else 0.0

    duplicate_rates = [_duplicate_rate(r.live_memory_contents) for r in runs]
    duplicate_rate = mean(duplicate_rates) if duplicate_rates else 0.0

    checkpoint_successes = sum(1 for r in runs if r.checkpoint_found and r.scenario.new_value in r.checkpoint_goal)
    checkpoint_rate = checkpoint_successes / n if n else 0.0

    injected_tokens = [len(r.aftermind_context.split()) for r in runs]
    avg_tokens = mean(injected_tokens) if injected_tokens else 0.0

    latencies_ms = sorted(r.recall_latency_seconds * 1000 for r in runs)
    avg_latency = mean(latencies_ms) if latencies_ms else 0.0
    p95_index = max(0, int(len(latencies_ms) * 0.95) - 1)
    p95_latency = latencies_ms[p95_index] if latencies_ms else 0.0

    return BenchmarkReport(
        n_scenarios=n,
        baseline_success_rate=baseline_successes / n if n else 0.0,
        aftermind_success_rate=aftermind_successes / n if n else 0.0,
        memory_precision=memory_precision,
        memory_recall=memory_recall,
        stale_memory_rate=stale_rate,
        duplicate_memory_rate=duplicate_rate,
        checkpoint_recovery_rate=checkpoint_rate,
        avg_injected_tokens=avg_tokens,
        avg_recall_latency_ms=avg_latency,
        p95_recall_latency_ms=p95_latency,
    )
