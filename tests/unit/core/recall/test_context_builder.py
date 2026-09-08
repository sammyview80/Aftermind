from core.recall.context_builder import ContextBuilder
from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory


def test_build_includes_checkpoint_section():
    checkpoint = Checkpoint(
        version=3,
        goal="Build the login flow",
        completed=["searched repo"],
        current="wiring session handling",
        blockers=["waiting on OAuth client secret"],
        next_steps=["add tests"],
    )

    context = ContextBuilder().build(checkpoint, [], ())

    assert "## Where you left off (v3)" in context
    assert "Goal: Build the login flow" in context
    assert "Completed: searched repo" in context
    assert "Current: wiring session handling" in context
    assert "Blockers: waiting on OAuth client secret" in context
    assert "Next: add tests" in context


def test_build_includes_ranked_memories_section():
    memories = [Memory(content="User prefers dark mode"), Memory(content="Team uses RabbitMQ")]
    context = ContextBuilder().build(None, memories, ())

    assert "## Relevant memories" in context
    assert "- User prefers dark mode" in context
    assert "- Team uses RabbitMQ" in context


def test_build_caps_memories_at_max_memories():
    memories = [Memory(content=f"fact {i}") for i in range(10)]
    context = ContextBuilder(max_memories=3).build(None, memories, ())

    assert context.count("- fact") == 3


def test_build_includes_related_entities_section():
    context = ContextBuilder().build(None, [], ("auth_module", "session"))
    assert "## Related entities" in context
    assert "auth_module, session" in context


def test_build_with_nothing_returns_empty_string():
    assert ContextBuilder().build(None, [], ()) == ""


def test_build_omits_empty_sections():
    context = ContextBuilder().build(None, [], ("entity_a",))
    assert "## Where you left off" not in context
    assert "## Relevant memories" not in context
    assert "## Related entities" in context
