from enum import Enum


class PreferenceSource(str, Enum):
    """How a preference observation was obtained — drives its starting
    confidence. An explicit instruction ("keep answers short") is trusted
    immediately; a repeated behavioral pattern needs several observations
    to earn the same trust; a single inference starts weakest of all."""

    EXPLICIT = "explicit"
    REPEATED = "repeated"
    INFERRED = "inferred"
