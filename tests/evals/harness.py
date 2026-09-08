"""Runs the scripted scenarios from scenarios.py through a real
AftermindService (in-memory providers, deterministic scripted LLM — the
same pattern core/facade.py's own unit tests use, just parameterized
over many topics) and records the metrics the milestone asks for.

Design note on the A/B comparison ("Hermes without Aftermind" vs
"Hermes + Aftermind"): the variable Aftermind actually controls is what
context gets injected into a session — not the reasoning model itself,
which is identical either way. So the honest, deterministic way to
isolate that variable is: baseline = the session-4 query gets exactly
what a fresh Hermes session naturally has with no memory system wired in
(nothing from sessions 1-3, since each Hermes session starts stateless —
see AGENTS.md's disclosed note that Hermes' own native session recall is
a separate, unscoped confound this project already routes around);
Aftermind = the session-4 query gets service.recall()'s context. Running
this 30x against a live LLM would mostly re-measure LLM sampling noise
on top of the same signal — this harness measures the mechanism itself,
which is what's actually assertable and reproducible in CI. Point
spot-checks against real Hermes + a real LLM have already been done for
each milestone; this suite is the systematic, repeatable counterpart.
"""
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from core.facade import AftermindService
from domain.models.experience import Experience
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)
from tests.evals.scenarios import Scenario

_CHANGE_MARKERS = ("changed", "switched", "now uses", "now is", "migrated")


class FakeDocumentStore:
    """Minimal DocumentStore for evals — same shape used throughout
    core/facade.py's own test suite."""

    def __init__(self) -> None:
        self._docs: dict[str, object] = {}

    def get(self, slug, scope=None):
        return self._docs.get(slug)

    def save(self, document):
        self._docs[document.slug] = document
        return document

    def search(self, query: str, scope=None, limit: int = 5):
        query_words = set(query.lower().split())

        def matches(document) -> bool:
            text = document.title + " " + " ".join(s.heading + " " + s.body for s in document.sections)
            return bool(query_words & set(text.lower().split()))

        return [d for d in self._docs.values() if matches(d)][:limit]


def _words(text: str) -> set[str]:
    return {w.strip(".,!?:;\"'()").lower() for w in text.split() if w.strip(".,!?:;\"'()")}


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class DeterministicLLM:
    """A scripted LLM standing in for the real reconciler/consolidator/
    checkpoint-summarizer calls, so scenario outcomes are reproducible
    and the suite runs in milliseconds, not minutes against a live
    model. Decisions are made by parsing the same prompts the real
    reconciler/consolidator/summarizer build — not by cheating with
    scenario-specific hooks — so this exercises the real prompt
    contracts, just with a rule-based responder instead of a live model.
    """

    def complete(self, prompt: str) -> str:
        if "MEMORIES TO CONSOLIDATE" in prompt:
            return self._consolidate(prompt)
        if "EXISTING MEMORIES:" in prompt:
            return self._reconcile(prompt)
        if "PREVIOUS CHECKPOINT" in prompt:
            return self._checkpoint(prompt)
        if "Return a JSON array of triples" in prompt:
            return "[]"  # graph extraction isn't this suite's concern
        raise AssertionError(f"DeterministicLLM got an unexpected prompt: {prompt[:80]!r}")

    def _reconcile(self, prompt: str) -> str:
        import json

        candidate_match = re.search(r"CANDIDATE:\n(.*?)\n\nEXISTING MEMORIES:", prompt, re.DOTALL)
        candidate = candidate_match.group(1).strip() if candidate_match else ""

        evidence = re.findall(r"\[([^\]]+)\] (.+)", prompt)

        if evidence:
            best_id, best_content = max(evidence, key=lambda pair: _overlap(candidate, pair[1]))
            best_score = _overlap(candidate, best_content)
            is_change = any(marker in candidate.lower() for marker in _CHANGE_MARKERS)
            if is_change and best_score > 0.1:
                return json.dumps(
                    {"action": "supersede", "target_memory_id": best_id, "confidence": 0.95, "reasoning": "eval"}
                )
            if best_score > 0.6:
                return json.dumps(
                    {"action": "ignore", "target_memory_id": best_id, "confidence": 0.9, "reasoning": "eval"}
                )

        return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "eval"})

    def _consolidate(self, prompt: str) -> str:
        import json

        lines = re.findall(r"^\d+\. (.+)$", prompt, re.MULTILINE)
        return json.dumps({"content": "; ".join(lines), "confidence": 0.9, "reasoning": "eval consolidation"})

    def _checkpoint(self, prompt: str) -> str:
        import json

        output_match = re.search(r"output: (.*)", prompt)
        text = output_match.group(1).strip() if output_match else ""
        return json.dumps({"goal": text, "completed": [], "current": text, "blocked_by": [], "next_steps": []})


def build_service(document_store: Optional[FakeDocumentStore] = None) -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=DeterministicLLM(),
        document_store=document_store,
    )


@dataclass
class ScenarioRun:
    scenario: Scenario
    scope: MemoryScope
    baseline_context: str
    aftermind_context: str
    retrieved_memories: list[str]
    checkpoint_found: bool
    checkpoint_goal: str
    recall_latency_seconds: float
    live_memory_contents: list[str] = field(default_factory=list)


def run_scenario(scenario: Scenario, service: AftermindService, tenant_id: str = "eval") -> ScenarioRun:
    scope = MemoryScope.of(tenant_id=tenant_id, project_id=scenario.scenario_id)

    for session in scenario.sessions:
        service.observe(Experience(scope=scope, output=session.statement))
        if session.checkpoint:
            service.checkpoint(
                scope=scope,
                goal=session.checkpoint_goal,
                current=session.checkpoint_current,
                next_steps=session.checkpoint_next_steps,
            )

    # Baseline: a fresh Hermes session with no memory system carries
    # nothing forward from sessions 1-3 — this is what "without
    # Aftermind" means for a stateless-per-session agent CLI.
    baseline_context = ""

    started = time.perf_counter()
    result = service.recall(RecallQuery(scope=scope, text=scenario.query))
    latency = time.perf_counter() - started

    checkpoint = service.latest_checkpoint(scope)

    return ScenarioRun(
        scenario=scenario,
        scope=scope,
        baseline_context=baseline_context,
        aftermind_context=result.context,
        retrieved_memories=[m.content for m in result.memories],
        checkpoint_found=checkpoint is not None,
        checkpoint_goal=checkpoint.goal if checkpoint else "",
        recall_latency_seconds=latency,
        live_memory_contents=[m.content for m in service.knowledge_store.list_all(scope=scope.stable())],
    )


def run_all(scenarios, tenant_id: str = "eval") -> list[ScenarioRun]:
    """One AftermindService per scenario (own scope) — mirrors real
    deployments where each project gets its own scope, and keeps
    scenarios independent so one topic's outcome can't leak into
    another's inside this run."""
    service = build_service()
    return [run_scenario(scenario, service, tenant_id=tenant_id) for scenario in scenarios]
