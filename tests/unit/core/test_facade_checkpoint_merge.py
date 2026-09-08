"""checkpoint_from_text must merge into the previous checkpoint, never
let a trivial session replace a substantive hand-off."""
import json

from core.facade import AftermindService
from core.observability import trace
from domain.models.scope import MemoryScope
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)


class ScriptedSummarizerLLM:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.response)


def _service(llm) -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=llm,
        tracer=trace.Tracer(sinks=[]),
    )


def _seed_v1(service, scope):
    return service.checkpoint(
        scope=scope,
        goal="Verify Claude Code recalls tetsaman memory",
        completed=["created repo", "seeded memory"],
        current="about to open Claude Code",
        next_steps=["open Claude Code", "verify recall"],
    )


def test_trivial_session_does_not_erase_previous_state():
    scope = MemoryScope.of(tenant_id="default", project_id="tetsaman")
    llm = ScriptedSummarizerLLM(
        {"goal": "", "completed": [], "current": "placeholder conversation, no memory written yet", "blocked_by": [], "next_steps": []}
    )
    service = _service(llm)
    _seed_v1(service, scope)

    v2 = service.checkpoint_from_text(scope=scope, text="User: hi\nAssistant: hello")

    assert v2.version == 2
    assert v2.goal == "Verify Claude Code recalls tetsaman memory"
    assert v2.completed == ("created repo", "seeded memory")
    assert v2.next_steps == ("open Claude Code", "verify recall")
    assert v2.current == "placeholder conversation, no memory written yet"


def test_progress_accumulates_and_finished_next_steps_drop_off():
    scope = MemoryScope.of(tenant_id="default", project_id="tetsaman")
    llm = ScriptedSummarizerLLM(
        {
            "goal": "Verify Claude Code recalls tetsaman memory",
            "completed": ["open Claude Code"],
            "current": "checking recall output",
            "blocked_by": ["recall timed out once"],
            "next_steps": ["verify recall", "raise recall timeout"],
        }
    )
    service = _service(llm)
    _seed_v1(service, scope)

    v2 = service.checkpoint_from_text(scope=scope, text="User: opened it\nAssistant: recall ran but timed out once")

    assert v2.completed == ("created repo", "seeded memory", "open Claude Code")
    assert v2.next_steps == ("verify recall", "raise recall timeout")
    assert v2.blockers == ("recall timed out once",)


def test_previous_completed_and_next_steps_are_in_the_summarizer_prompt():
    scope = MemoryScope.of(tenant_id="default", project_id="tetsaman")
    llm = ScriptedSummarizerLLM({"goal": "g", "completed": [], "current": "c", "blocked_by": [], "next_steps": []})
    service = _service(llm)
    _seed_v1(service, scope)

    service.checkpoint_from_text(scope=scope, text="User: status?\nAssistant: still going")

    prompt = llm.prompts[-1]
    assert "seeded memory" in prompt
    assert "verify recall" in prompt


def test_first_checkpoint_without_previous_is_unchanged():
    scope = MemoryScope.of(tenant_id="default", project_id="fresh")
    llm = ScriptedSummarizerLLM({"goal": "g", "completed": ["a"], "current": "c", "blocked_by": [], "next_steps": ["n"]})
    service = _service(llm)

    v1 = service.checkpoint_from_text(scope=scope, text="User: x\nAssistant: y")

    assert (v1.goal, v1.completed, v1.next_steps) == ("g", ("a",), ("n",))
