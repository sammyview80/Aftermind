from enum import Enum


class ExperienceOutcome(str, Enum):
    """How an experience concluded, independent of whether it's worth
    remembering — that judgment belongs to candidate extraction, not here."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
