from typing import Any, Optional

from core.facade import AftermindService
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope

"""Framework-neutral tool logic for the four MCP tools. Kept separate
from apps/api/mcp/server.py (which imports the `mcp` package) so these
are plain, directly unit-testable functions with no MCP dependency."""


def _scope(levels: Optional[dict[str, str]]) -> Optional[MemoryScope]:
    return MemoryScope.of(**levels) if levels else None


def _summarize_memory(memory) -> dict[str, Any]:
    return {
        "memory_id": memory.memory_id,
        "content": memory.content,
        "memory_type": memory.memory_type.value,
        "confidence": memory.confidence,
    }


def memory_observe(
    service: AftermindService,
    scope: Optional[dict[str, str]] = None,
    input: str = "",
    output: str = "",
    event_type: str = EventType.AGENT_MESSAGE.value,
) -> dict[str, Any]:
    """Learn from one turn of agent experience."""
    experience = Experience(
        scope=_scope(scope), events=[Event(event_type=EventType(event_type))], input=input, output=output
    )
    memory = service.observe(experience)
    if memory is None:
        return {"created": False}
    return {"created": True, **_summarize_memory(memory)}


def memory_recall(
    service: AftermindService, scope: Optional[dict[str, str]] = None, text: str = "", limit: int = 10
) -> dict[str, Any]:
    """Reconstruct context — latest checkpoint + relevant memories —
    for a request, e.g. "continue where we left off"."""
    result = service.recall(RecallQuery(scope=_scope(scope), text=text, limit=limit))
    return {
        "context": result.context,
        "memories": [_summarize_memory(m) for m in result.memories],
        "related_entities": list(result.related_entities),
    }


def memory_checkpoint(
    service: AftermindService,
    scope: Optional[dict[str, str]] = None,
    goal: str = "",
    current: str = "",
    completed: Optional[list[str]] = None,
    blockers: Optional[list[str]] = None,
    next_steps: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Explicitly record a checkpoint of where the agent's work stands."""
    checkpoint = service.checkpoint(
        scope=_scope(scope),
        goal=goal,
        current=current,
        completed=completed or [],
        blockers=blockers or [],
        next_steps=next_steps or [],
        reason="mcp_manual",
    )
    return {"checkpoint_id": checkpoint.checkpoint_id, "version": checkpoint.version, "goal": checkpoint.goal}


def memory_search(
    service: AftermindService, scope: Optional[dict[str, str]] = None, query: str = "", limit: int = 5
) -> dict[str, Any]:
    """Direct memory search, no checkpoint or context compression."""
    memories = service.search(query, scope=_scope(scope), limit=limit)
    return {"memories": [_summarize_memory(m) for m in memories]}
