from typing import Optional

from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory

DEFAULT_MAX_MEMORIES = 5
DEFAULT_MAX_ENTITIES = 10


class ContextBuilder:
    """Compresses a checkpoint, ranked memories, and related entities into
    one compact block of context text for the agent to resume from."""

    def __init__(self, max_memories: int = DEFAULT_MAX_MEMORIES, max_entities: int = DEFAULT_MAX_ENTITIES) -> None:
        self._max_memories = max_memories
        self._max_entities = max_entities

    def build(
        self,
        checkpoint: Optional[Checkpoint],
        ranked_memories: list[Memory],
        related_entities: tuple[str, ...] = (),
        relationships: tuple[tuple[str, str, str], ...] = (),
        historical_memories: tuple[Memory, ...] = (),
        knowledge_excerpts: tuple[str, ...] = (),
    ) -> str:
        """Fuse checkpoint + current facts + historical facts +
        relationships + consolidated knowledge + related entities into
        one compact block — one clean context package, not one blob per
        source. Sections that have nothing to say are simply omitted."""
        sections: list[str] = []

        if checkpoint is not None:
            sections.append(self._checkpoint_section(checkpoint))

        included = ranked_memories[: self._max_memories]
        if included:
            lines = "\n".join(f"- {m.content}" for m in included)
            sections.append(f"## Current facts\n{lines}")

        if historical_memories:
            lines = "\n".join(f"- {m.content} (superseded)" for m in historical_memories[: self._max_memories])
            sections.append(f"## Recent history\n{lines}")

        if relationships:
            lines = "\n".join(f"- {s} -[{r}]-> {t}" for s, r, t in relationships[: self._max_entities])
            sections.append(f"## Relationships\n{lines}")

        if knowledge_excerpts:
            lines = "\n\n".join(knowledge_excerpts)
            sections.append(f"## From company knowledge\n{lines}")

        if related_entities:
            entities = ", ".join(related_entities[: self._max_entities])
            sections.append(f"## Related entities\n{entities}")

        return "\n\n".join(sections)

    def _checkpoint_section(self, checkpoint: Checkpoint) -> str:
        lines = [f"## Where you left off (v{checkpoint.version})"]
        if checkpoint.goal:
            lines.append(f"Goal: {checkpoint.goal}")
        if checkpoint.completed:
            lines.append("Completed: " + "; ".join(checkpoint.completed))
        if checkpoint.current:
            lines.append(f"Current: {checkpoint.current}")
        if checkpoint.blockers:
            lines.append("Blockers: " + "; ".join(checkpoint.blockers))
        if checkpoint.next_steps:
            lines.append("Next: " + "; ".join(checkpoint.next_steps))
        return "\n".join(lines)
