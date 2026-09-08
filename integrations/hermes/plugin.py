from typing import Any, Optional

from core.checkpoints.summarizer import CheckpointSummarizer
from core.facade import AftermindService
from domain.enums.event_type import EventType
from domain.models.experience import Experience
from domain.models.external_identity import ExternalIdentity
from domain.models.recall_query import RecallQuery
from integrations.hermes.checkpoint_adapter import to_hermes_checkpoint
from integrations.hermes.event_mapper import map_hermes_event
from integrations.hermes.scope_mapper import map_hermes_scope


def _summarize_memory(memory) -> dict[str, Any]:
    return {"memory_id": memory.memory_id, "content": memory.content, "confidence": memory.confidence}


class HermesMemoryPlugin:
    """First real framework adapter: wires Hermes' native events/context
    into AftermindService via event_mapper/scope_mapper/
    checkpoint_adapter. This is the seam — nothing in core/ or domain/
    knows Hermes exists; everything Hermes-specific lives here.
    """

    def __init__(self, service: AftermindService, identities: Optional[dict[str, ExternalIdentity]] = None) -> None:
        self._service = service
        self._identities = identities or {}
        self._summarizer = CheckpointSummarizer()

    def on_event(self, hermes_event: dict, hermes_context: dict) -> dict[str, Any]:
        """Called per Hermes event — the "learn" path."""
        scope = map_hermes_scope(hermes_context, self._identities)
        event = map_hermes_event(hermes_event)
        text = event.payload.get("text", "")
        experience = Experience(
            scope=scope,
            events=[event],
            input=text if event.event_type == EventType.USER_MESSAGE else "",
            output=text if event.event_type == EventType.AGENT_MESSAGE else "",
        )
        memory = self._service.observe(experience)
        if memory is None:
            return {"created": False}
        return {"created": True, **_summarize_memory(memory)}

    def on_session_finalize(self, hermes_context: dict, hermes_events: list[dict]) -> dict[str, Any]:
        """Called from Hermes' on_session_finalize hook — the
        "checkpoint trigger -> checkpoint summarizer -> checkpoint
        manager -> store versioned checkpoint" path."""
        scope = map_hermes_scope(hermes_context, self._identities)
        events = [map_hermes_event(e) for e in hermes_events]
        last_agent_text = next(
            (e.payload.get("text", "") for e in reversed(events) if e.event_type == EventType.AGENT_MESSAGE), ""
        )
        experience = Experience(scope=scope, events=events, output=last_agent_text)
        summary = self._summarizer.summarize(experience)

        checkpoint = self._service.checkpoint(
            scope=scope,
            goal=summary.goal,
            current=summary.current,
            completed=summary.completed,
            blockers=summary.blockers,
            next_steps=summary.next_steps,
            reason="hermes_session_finalize",
        )
        return to_hermes_checkpoint(checkpoint)

    def on_recall_request(self, hermes_context: dict, text: str, limit: int = 10) -> dict[str, Any]:
        """Called when Hermes wants to resume — "continue where I left off"."""
        scope = map_hermes_scope(hermes_context, self._identities)
        result = self._service.recall(RecallQuery(scope=scope, text=text, limit=limit))
        return {
            "context": result.context,
            "memories": [_summarize_memory(m) for m in result.memories],
            "related_entities": list(result.related_entities),
        }
