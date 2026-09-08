"""Per-operation tracing for Aftermind's memory pipeline.

One `OperationTrace` covers one public operation (observe, recall,
checkpoint, sync job) end to end, and records what actually happened
at each store boundary — SQLite write, Neo4j sync, OpenKnowledge sync,
checkpoint, LLM latency — so a single Hermes turn can be inspected as:

    observe abc123 scope=hermes:*:aftermind
      candidate_count=1 reconciliation_action=update
      sqlite_write=ok neo4j_sync=ok openknowledge_sync=skipped
      llm_calls=2 llm_latency_ms=1840 latency_ms=1912

Traces are propagated through a contextvar so deep pipeline stages
(the LLM wrapper, the sync dispatcher) attach to the active trace
without threading it through every signature. A nested `begin()` for
an already-active trace joins it rather than starting a second one,
so a REST handler can open the trace, call the facade (which also
calls begin()), and read the same trace back for the response.

Everything here is pure logic over the standard library; sinks decide
where a finished trace goes (structured log line, in-memory ring
buffer for /traces, ...).
"""
import json
import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional, Protocol
from uuid import uuid4

_LOG = logging.getLogger("aftermind.trace")

# Values a sync/store field can take. Deliberately strings, not an enum:
# they are written straight into logs/responses and read by humans.
OK = "ok"
FAILED = "failed"
PENDING = "pending"  # durable job exists, will be retried by the worker
SKIPPED = "skipped"  # nothing to do (no store configured, no triples, ...)


@dataclass
class Span:
    name: str
    started_at: float
    latency_ms: Optional[float] = None
    status: str = OK
    error: Optional[str] = None


@dataclass
class OperationTrace:
    """Mutable recorder for one operation. `fields` is the flat, user-
    facing summary (candidate_count, neo4j_sync=ok, ...); `spans` is the
    timed breakdown underneath it."""

    operation: str
    scope: Optional[str] = None
    trace_id: str = field(default_factory=lambda: uuid4().hex[:16])
    parent_trace_id: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fields: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    status: str = OK
    error: Optional[str] = None
    latency_ms: Optional[float] = None
    _clock_start: float = field(default_factory=time.perf_counter, repr=False)

    def record(self, **fields: Any) -> None:
        self.fields.update(fields)

    def increment(self, key: str, by: float = 1) -> None:
        self.fields[key] = self.fields.get(key, 0) + by

    def append(self, key: str, value: Any) -> None:
        self.fields.setdefault(key, [])
        if value not in self.fields[key]:
            self.fields[key].append(value)

    @contextmanager
    def span(self, name: str, reraise: bool = True) -> Iterator[Span]:
        """Time one stage. On exception the span is marked failed and,
        unless `reraise=False`, the exception propagates — callers doing
        failure isolation pass reraise=False and check span.status."""
        span = Span(name=name, started_at=time.perf_counter())
        self.spans.append(span)
        try:
            yield span
        except Exception as exc:  # noqa: BLE001 - recorded, then decided by caller
            span.status = FAILED
            span.error = f"{type(exc).__name__}: {exc}"
            if reraise:
                raise
        finally:
            span.latency_ms = round((time.perf_counter() - span.started_at) * 1000, 2)

    def finish(self, error: Optional[BaseException] = None) -> None:
        self.latency_ms = round((time.perf_counter() - self._clock_start) * 1000, 2)
        if error is not None:
            self.status = FAILED
            self.error = f"{type(error).__name__}: {error}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "parent_trace_id": self.parent_trace_id,
            "operation": self.operation,
            "scope": self.scope,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "latency_ms": self.latency_ms,
            **self.fields,
            "spans": [
                {"name": s.name, "latency_ms": s.latency_ms, "status": s.status, "error": s.error} for s in self.spans
            ],
        }


class TraceSink(Protocol):
    def emit(self, trace: OperationTrace) -> None: ...


class LoggingTraceSink:
    """One structured JSON line per finished trace on the
    `aftermind.trace` logger — greppable by trace_id, ingestible by any
    log shipper. Level is INFO for ok, WARNING when anything failed or
    was left pending, so a default INFO logger surfaces both."""

    def __init__(self, logger: logging.Logger = _LOG) -> None:
        self._logger = logger

    def emit(self, trace: OperationTrace) -> None:
        payload = trace.to_dict()
        degraded = trace.status != OK or any(
            v in (FAILED, PENDING) for k, v in trace.fields.items() if isinstance(v, str)
        )
        self._logger.log(logging.WARNING if degraded else logging.INFO, json.dumps(payload, default=str))


class InMemoryTraceSink:
    """Ring buffer of the most recent traces, for the /traces debug
    endpoint and for tests. Thread-safe; bounded so a long-running
    process never grows without limit."""

    def __init__(self, maxlen: int = 200) -> None:
        self._traces: deque[OperationTrace] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def emit(self, trace: OperationTrace) -> None:
        with self._lock:
            self._traces.append(trace)

    def recent(self, limit: int = 50, operation: Optional[str] = None) -> list[OperationTrace]:
        with self._lock:
            traces = list(self._traces)
        if operation:
            traces = [t for t in traces if t.operation == operation]
        return list(reversed(traces))[:limit]

    def get(self, trace_id: str) -> Optional[OperationTrace]:
        with self._lock:
            return next((t for t in self._traces if t.trace_id == trace_id), None)

    def clear(self) -> None:
        with self._lock:
            self._traces.clear()


_current: ContextVar[Optional[OperationTrace]] = ContextVar("aftermind_trace", default=None)


class Tracer:
    """Owns the sinks and the begin()/current() API. One instance per
    process is the norm (see `default_tracer`), but tests build their own
    with an InMemoryTraceSink to assert on what was recorded."""

    def __init__(self, sinks: Optional[list[TraceSink]] = None) -> None:
        self.sinks: list[TraceSink] = sinks if sinks is not None else [LoggingTraceSink()]

    @staticmethod
    def current() -> Optional[OperationTrace]:
        return _current.get()

    @contextmanager
    def begin(self, operation: str, scope: Optional[str] = None, **fields: Any) -> Iterator[OperationTrace]:
        """Start a trace, or join the active one. Joining records the
        nested operation as a span on the parent rather than emitting a
        separate trace, so one REST call = one trace."""
        active = _current.get()
        if active is not None:
            with active.span(operation):
                active.record(**fields)
                yield active
            return

        trace = OperationTrace(operation=operation, scope=scope, fields=dict(fields))
        token = _current.set(trace)
        try:
            yield trace
        except BaseException as exc:
            trace.finish(error=exc)
            raise
        else:
            trace.finish()
        finally:
            _current.reset(token)
            self._emit(trace)

    @contextmanager
    def child(self, operation: str, parent_trace_id: Optional[str], scope: Optional[str] = None, **fields: Any):
        """A separate trace linked to a parent by id — for work that
        runs later on another thread (a retried sync job) and so can't
        join the parent's context."""
        trace = OperationTrace(operation=operation, scope=scope, parent_trace_id=parent_trace_id, fields=dict(fields))
        token = _current.set(trace)
        try:
            yield trace
        except BaseException as exc:
            trace.finish(error=exc)
            raise
        else:
            trace.finish()
        finally:
            _current.reset(token)
            self._emit(trace)

    def _emit(self, trace: OperationTrace) -> None:
        for sink in self.sinks:
            try:
                sink.emit(trace)
            except Exception:  # noqa: BLE001 - a broken sink must never break the operation
                _LOG.exception("trace sink %r failed", sink)


def record(**fields: Any) -> None:
    """Attach fields to the active trace, if any. Safe to call from
    anywhere in the pipeline — a no-op outside a trace."""
    trace = _current.get()
    if trace is not None:
        trace.record(**fields)


def increment(key: str, by: float = 1) -> None:
    trace = _current.get()
    if trace is not None:
        trace.increment(key, by)


def append(key: str, value: Any) -> None:
    trace = _current.get()
    if trace is not None:
        trace.append(key, value)


@contextmanager
def span(name: str, reraise: bool = True) -> Iterator[Optional[Span]]:
    """Time a stage on the active trace; yields None (and still runs the
    block) when no trace is active."""
    trace = _current.get()
    if trace is None:
        yield None
        return
    with trace.span(name, reraise=reraise) as s:
        yield s


default_tracer = Tracer()
