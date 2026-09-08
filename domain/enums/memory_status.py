from enum import Enum


class MemoryStatus(str, Enum):
    """Where a memory sits in its lifecycle — separate from whether it's
    factually superseded (Memory.superseded_by), since a memory can be
    factually current but still decay from disuse, or be archived
    without being factually wrong."""

    ACTIVE = "active"  # healthy, eligible for recall
    DECAYED = "decayed"  # unused long enough to be deprioritized, still eligible
    ARCHIVED = "archived"  # superseded or manually archived, excluded from active recall
    EXPIRED = "expired"  # decayed past the expiry threshold or past valid_until
    FORGOTTEN = "forgotten"  # explicitly deleted; provenance cascade applied
