from typing import Optional

from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory
from domain.models.preference import Preference

DEFAULT_MAX_MEMORIES = 5
DEFAULT_MAX_ENTITIES = 10
# Below this, a preference is still gathering evidence — injecting it
# into every response would let a single offhand remark steer behavior
# before it's actually earned that trust.
DEFAULT_MIN_PREFERENCE_CONFIDENCE = 0.5

_VERBOSITY_TEXT = {
    "short": "Keep answers concise.",
    "detailed": "Prefer detailed, thorough explanations.",
}
_STRUCTURE_TEXT = {
    "stepwise": "Prefer direct, stepwise implementation steps over narrative explanation.",
}


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
        preferences: tuple[Preference, ...] = (),
    ) -> str:
        """Fuse checkpoint + current facts + historical facts +
        relationships + consolidated knowledge + related entities into
        one compact block — one clean context package, not one blob per
        source. Sections that have nothing to say are simply omitted."""
        sections: list[str] = []

        if checkpoint is not None:
            sections.append(self._checkpoint_section(checkpoint))

        style_lines = self._user_style_lines(preferences)
        if style_lines:
            sections.append("## User style\n" + "\n".join(style_lines))

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

    def _user_style_lines(self, preferences: tuple[Preference, ...]) -> list[str]:
        """Render only the preferences trusted enough to act on (see
        `DEFAULT_MIN_PREFERENCE_CONFIDENCE`) as plain instruction lines,
        not raw dimension/value pairs — the LLM should read this like a
        style note, not a data dump.

        The heuristic signals (`core/preferences/signals.py`) always
        produce the same fixed value shape, so those get a hand-written,
        natural-language phrasing. The LLM reconciler's output shape is
        not fixed the same way (it's free to name new dimensions and
        value keys it infers from context) — those fall back to a
        generic "<dimension>: <value>" rendering so a preference the LLM
        found never silently disappears from context just because it
        doesn't match a hardcoded template."""
        lines: list[str] = []
        for pref in preferences:
            if pref.confidence < DEFAULT_MIN_PREFERENCE_CONFIDENCE:
                continue
            text = self._known_style_text(pref) or self._generic_style_text(pref)
            if text:
                lines.append(f"- {text}")
        return lines

    def _known_style_text(self, pref: Preference) -> Optional[str]:
        if pref.dimension == "response_style.verbosity":
            return _VERBOSITY_TEXT.get(pref.value.get("verbosity"))
        if pref.dimension == "response_style.structure":
            return _STRUCTURE_TEXT.get(pref.value.get("structure"))
        return None

    def _generic_style_text(self, pref: Preference) -> Optional[str]:
        if not pref.value:
            return None
        label = pref.dimension.removeprefix("response_style.").replace("_", " ").replace(".", " ")
        details = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in pref.value.items())
        return f"{label.capitalize()} — {details}"
