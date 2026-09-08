import json
import logging

import pytest

from core.observability import trace
from core.observability.llm import TracedLLMProvider
from core.observability.logging_setup import JsonFormatter


def _tracer():
    sink = trace.InMemoryTraceSink()
    return trace.Tracer(sinks=[sink]), sink


def test_begin_records_fields_latency_and_emits_to_sinks():
    tracer, sink = _tracer()

    with tracer.begin("observe", scope="t1:*") as t:
        t.record(candidate_count=2, sqlite_write=trace.OK)
        with t.span("reconcile"):
            pass

    emitted = sink.recent()
    assert len(emitted) == 1
    got = emitted[0].to_dict()
    assert got["operation"] == "observe"
    assert got["scope"] == "t1:*"
    assert got["candidate_count"] == 2
    assert got["sqlite_write"] == "ok"
    assert got["status"] == "ok"
    assert got["latency_ms"] is not None
    assert got["spans"][0]["name"] == "reconcile"
    assert trace.Tracer.current() is None  # context restored


def test_nested_begin_joins_the_active_trace_instead_of_emitting_twice():
    tracer, sink = _tracer()

    with tracer.begin("rest.observe") as outer:
        with tracer.begin("observe") as inner:
            inner.record(memory_id="m1")
        assert inner is outer

    assert len(sink.recent()) == 1
    assert sink.recent()[0].fields["memory_id"] == "m1"
    assert [s.name for s in sink.recent()[0].spans] == ["observe"]


def test_exception_marks_trace_failed_and_still_propagates():
    tracer, sink = _tracer()

    with pytest.raises(RuntimeError):
        with tracer.begin("recall"):
            raise RuntimeError("boom")

    got = sink.recent()[0]
    assert got.status == trace.FAILED
    assert "RuntimeError: boom" == got.error


def test_span_with_reraise_false_swallows_and_records_failure():
    tracer, sink = _tracer()

    with tracer.begin("observe") as t:
        with t.span("neo4j", reraise=False) as span:
            raise ConnectionError("down")
        assert span.status == trace.FAILED
        assert "ConnectionError" in span.error

    assert sink.recent()[0].status == trace.OK  # the operation itself succeeded


def test_module_level_helpers_are_noops_outside_a_trace():
    trace.record(x=1)
    trace.increment("n")
    trace.append("list", "a")
    with trace.span("nothing") as s:
        assert s is None


def test_child_trace_links_to_parent_by_id():
    tracer, sink = _tracer()
    with tracer.child("sync_job", parent_trace_id="abc") as t:
        t.record(kind="graph_sync")
    got = sink.recent()[0]
    assert got.parent_trace_id == "abc"
    assert got.operation == "sync_job"


def test_traced_llm_provider_accumulates_calls_and_latency():
    tracer, sink = _tracer()

    class Slow:
        def complete(self, prompt):
            return "ok"

    llm = TracedLLMProvider(Slow())
    with tracer.begin("observe"):
        llm.complete("a")
        llm.complete("b")

    got = sink.recent()[0]
    assert got.fields["llm_calls"] == 2
    assert got.fields["llm_latency_ms"] >= 0
    assert [s.name for s in got.spans] == ["llm.complete", "llm.complete"]


def test_traced_llm_provider_records_even_when_the_call_fails():
    tracer, sink = _tracer()

    class Broken:
        def complete(self, prompt):
            raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        with tracer.begin("observe"):
            TracedLLMProvider(Broken()).complete("x")

    got = sink.recent()[0]
    assert got.fields["llm_calls"] == 1
    assert got.spans[0].status == trace.FAILED


def test_logging_sink_emits_one_json_line_and_warns_on_pending():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    logger = logging.getLogger("test.aftermind.trace")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(Capture())
    logger.propagate = False

    tracer = trace.Tracer(sinks=[trace.LoggingTraceSink(logger)])
    with tracer.begin("observe") as t:
        t.record(neo4j_sync=trace.PENDING)

    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    payload = json.loads(records[0].getMessage())
    assert payload["neo4j_sync"] == "pending"


def test_in_memory_sink_is_bounded_and_filterable():
    sink = trace.InMemoryTraceSink(maxlen=2)
    tracer = trace.Tracer(sinks=[sink])
    for op in ("observe", "recall", "observe"):
        with tracer.begin(op):
            pass
    assert len(sink.recent()) == 2
    assert [t.operation for t in sink.recent(operation="observe")] == ["observe"]


def test_json_formatter_embeds_trace_payload_as_object():
    formatter = JsonFormatter()
    record = logging.LogRecord("aftermind.trace", logging.INFO, __file__, 1, json.dumps({"trace_id": "x"}), (), None)
    out = json.loads(formatter.format(record))
    assert out["trace"]["trace_id"] == "x"
    assert out["logger"] == "aftermind.trace"
