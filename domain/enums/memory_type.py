from enum import Enum


class MemoryType(str, Enum):
    """Classification of a stored memory."""

    SEMANTIC = "semantic"      # facts, preferences, stable knowledge
    EPISODIC = "episodic"      # specific past events/experiences
    PROCEDURAL = "procedural"  # how-to, learned behaviors/skills
