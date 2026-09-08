import time

from core.observability import trace
from domain.interfaces.llm_provider import LLMProvider


class TracedLLMProvider:
    """Wraps any LLMProvider and accounts every call to the active trace:
    llm_calls, llm_latency_ms (cumulative), plus one timed span per call
    so a slow observe() can be attributed to reconciliation vs. triple
    extraction vs. consolidation. Transparent when no trace is active."""

    def __init__(self, inner: LLMProvider, name: str = "llm") -> None:
        self._inner = inner
        self._name = name

    def complete(self, prompt: str) -> str:
        started = time.perf_counter()
        try:
            with trace.span(f"{self._name}.complete"):
                return self._inner.complete(prompt)
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            trace.increment("llm_calls")
            trace.increment("llm_latency_ms", elapsed_ms)
