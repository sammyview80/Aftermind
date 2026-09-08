from typing import Any

from core.checkpoints.summarizer import CheckpointSummary
from domain.models.checkpoint import Checkpoint

"""Converts between Aftermind's Checkpoint and Hermes' checkpoint shape.

Hermes' shape matches providers/llm/prompts/checkpoint.md's output
fields exactly (goal/completed/current/blocked_by/next_steps) —
Aftermind names the third field `blockers`, Hermes/the prompt calls it
`blocked_by`; this is the one seam that translates between them.
"""


def to_hermes_checkpoint(checkpoint: Checkpoint) -> dict[str, Any]:
    return {
        "goal": checkpoint.goal,
        "completed": list(checkpoint.completed),
        "current": checkpoint.current,
        "blocked_by": list(checkpoint.blockers),
        "next_steps": list(checkpoint.next_steps),
        "version": checkpoint.version,
    }


def from_hermes_checkpoint(data: dict[str, Any]) -> CheckpointSummary:
    """Build a CheckpointSummary from a Hermes-shaped checkpoint dict —
    e.g. one Hermes produced itself via the checkpoint.md prompt — ready
    to hand to CheckpointManager.create()."""
    return CheckpointSummary(
        goal=data.get("goal", ""),
        completed=tuple(data.get("completed", ())),
        current=data.get("current", ""),
        blockers=tuple(data.get("blocked_by", ())),
        next_steps=tuple(data.get("next_steps", ())),
    )
