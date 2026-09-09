import re
from typing import NamedTuple

# Deliberately simple, deterministic pattern matching rather than an LLM
# call — behavior/preference extraction runs on every observe(), so it
# has to be cheap. It only needs to catch clear, common phrasings;
# anything subtler stays unrecognized rather than guessed at, since a
# wrong signal here corrupts a profile that's supposed to be
# conservative and evidence-based.

_SHORT_PATTERNS = (
    re.compile(r"\bdon'?t give me long answers\b", re.IGNORECASE),
    re.compile(r"\bkeep (it|answers?|responses?) short\b", re.IGNORECASE),
    re.compile(r"\bbe (more )?(brief|concise|terse)\b", re.IGNORECASE),
    re.compile(r"\bshort(er)? answers?\b", re.IGNORECASE),
    re.compile(r"^\s*short\.?\s*$", re.IGNORECASE),
    re.compile(r"\bno (long )?preambles?\b", re.IGNORECASE),
    re.compile(r"\bstop (summarizing|the summaries)\b", re.IGNORECASE),
)

_DETAILED_PATTERNS = (
    re.compile(r"\b(give|want) (me )?(more )?detail\b", re.IGNORECASE),
    re.compile(r"\bmore detailed\b", re.IGNORECASE),
    re.compile(r"\bexplain (this |that )?(in depth|thoroughly|fully)\b", re.IGNORECASE),
    re.compile(r"\bwalk me through\b", re.IGNORECASE),
    re.compile(r"\barchitecture breakdown\b", re.IGNORECASE),
)

_STEPWISE_PATTERNS = (
    re.compile(r"\bjust tell me the steps\b", re.IGNORECASE),
    re.compile(r"\bwhat('s| is) next\??\b", re.IGNORECASE),
    re.compile(r"\bgive me (the )?steps\b", re.IGNORECASE),
)


class PreferenceSignal(NamedTuple):
    dimension: str
    value: dict
    explicit: bool


def extract_signals(text: str) -> tuple[PreferenceSignal, ...]:
    """Scan one turn of raw text for recognizable response-style
    preference statements. Matches are treated as explicit — they're
    direct instructions/requests about how to respond, not incidental
    behavior — so `PreferenceManager.observe` weighs them heavily from
    the first occurrence."""
    if not text:
        return ()

    # Each facet of response style is its own dimension (not merged keys
    # of one "response_style" dict) so that observing one facet (e.g.
    # structure=stepwise) never supersedes an unrelated facet (e.g.
    # verbosity=short) just because the value dict as a whole differs.
    signals: list[PreferenceSignal] = []
    if any(p.search(text) for p in _SHORT_PATTERNS):
        signals.append(PreferenceSignal("response_style.verbosity", {"verbosity": "short"}, True))
    if any(p.search(text) for p in _DETAILED_PATTERNS):
        signals.append(PreferenceSignal("response_style.verbosity", {"verbosity": "detailed"}, True))
    if any(p.search(text) for p in _STEPWISE_PATTERNS):
        signals.append(PreferenceSignal("response_style.structure", {"structure": "stepwise"}, True))
    return tuple(signals)
