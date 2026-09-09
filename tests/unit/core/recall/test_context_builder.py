from core.recall.context_builder import ContextBuilder
from domain.enums.preference_source import PreferenceSource
from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory
from domain.models.preference import Preference


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

    assert "## Current facts" in context
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
    assert "## Current facts" not in context
    assert "## Related entities" in context


def test_build_includes_historical_memories_as_superseded():
    historical = [Memory(content="Billing used Redis before")]
    context = ContextBuilder().build(None, [], (), historical_memories=tuple(historical))

    assert "## Recent history" in context
    assert "- Billing used Redis before (superseded)" in context


def test_build_includes_relationships_section():
    relationships = (("RabbitMQ", "part_of", "payments architecture"),)
    context = ContextBuilder().build(None, [], (), relationships=relationships)

    assert "## Relationships" in context
    assert "- RabbitMQ -[part_of]-> payments architecture" in context


def test_build_includes_knowledge_excerpts_section():
    context = ContextBuilder().build(None, [], (), knowledge_excerpts=("### Billing Architecture\nUses RabbitMQ.",))

    assert "## From company knowledge" in context
    assert "### Billing Architecture" in context
    assert "Uses RabbitMQ." in context


def test_build_includes_user_style_section_for_confident_preferences():
    preferences = (
        Preference(
            dimension="response_style.verbosity",
            value={"verbosity": "short"},
            confidence=0.9,
            source=PreferenceSource.EXPLICIT,
        ),
    )
    context = ContextBuilder().build(None, [], (), preferences=preferences)

    assert "## User style" in context
    assert "Keep answers concise." in context


def test_build_falls_back_to_generic_rendering_for_llm_shaped_preferences():
    preferences = (
        Preference(dimension="response_style.technical_depth", value={"value": "code_only"}, confidence=0.9),
    )
    context = ContextBuilder().build(None, [], (), preferences=preferences)

    assert "## User style" in context
    assert "technical depth" in context.lower()
    assert "code_only" in context


def test_build_omits_low_confidence_preferences():
    preferences = (Preference(dimension="response_style.verbosity", value={"verbosity": "short"}, confidence=0.2),)
    context = ContextBuilder().build(None, [], (), preferences=preferences)

    assert "## User style" not in context


def test_build_fuses_all_sources_into_one_compact_context():
    checkpoint = Checkpoint(version=1, goal="Migrate billing workers", current="in progress")
    current = [Memory(content="Billing now uses RabbitMQ")]
    historical = [Memory(content="Billing used Redis before")]
    relationships = (("RabbitMQ", "part_of", "payments architecture"),)
    excerpts = ("### Billing Architecture\nRabbitMQ backs billing.",)

    context = ContextBuilder().build(
        checkpoint, current, ("RabbitMQ",), relationships=relationships, historical_memories=historical,
        knowledge_excerpts=excerpts,
    )

    # One package, sections in a stable, readable order.
    assert context.index("## Where you left off") < context.index("## Current facts")
    assert context.index("## Current facts") < context.index("## Recent history")
    assert context.index("## Recent history") < context.index("## Relationships")
    assert context.index("## Relationships") < context.index("## From company knowledge")
    assert context.index("## From company knowledge") < context.index("## Related entities")
