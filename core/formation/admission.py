"""Memory admission policy: what may become a memory, what never does.

This is the deterministic half of "what should be stored". It runs
before any LLM call, on every observation, and is the same for every
adapter (Claude Code, Codex, Hermes, REST, MCP). Everything it rejects
stays in the experiences log (raw history is kept) but never reaches
reconciliation or the memories table.

    KEEP (candidates for memory)            REJECT (stay in experiences only)
    ------------------------------------    -----------------------------------------
    decisions ("we decided X")              questions ("what db do we use?")
    facts about the project/system          directives to the agent ("restart it")
    stable preferences and requirements     greetings, acknowledgements, filler
    corrections ("no, it's tsk not tetsaman") agent progress narration ("Let me…", "Done.")
    discoveries and root causes             tool output dumps, code, stack traces, JSON
    ownership / naming / conventions        markup / system payloads / cross-agent chatter
                                            secrets (keys, tokens, passwords) — always
                                            over-long blobs (not atomic; LLM must extract)

The LLM admission stage (admission_llm.py) does the *semantic* half —
pulling atomic facts out of long messages and judging usefulness — but
only for text this gate lets through, and its output is gated again.
"""
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from domain.enums.event_type import EventType

DEFAULT_MAX_CANDIDATE_CHARS = 600

# ---------------------------------------------------------------- lexicons

_INTERROGATIVE_STARTS = frozenset(
    "what why how when where who whom whose which is are am was were do does did can could "
    "should would will shall may might have has had isn't aren't don't doesn't didn't can't "
    "couldn't shouldn't wouldn't won't".split()
)

_REQUEST_LEADS = (
    "also", "please", "pls", "okay", "ok", "now", "next", "then", "just", "let's", "lets",
    "can you", "could you", "would you", "will you", "i want", "i need", "i'd like", "we need",
    "make sure", "go ahead", "try to", "don't", "do not", "kindly", "you should", "you need to",
)
_IMPERATIVE_VERBS = frozenset(
    """add build change check clean commit configure create debug delete deploy do document
    ensure explain fix generate give help implement install investigate keep list look make
    merge move open push read refactor remove rename restart run save search set show start
    stop test try update upgrade use verify write tell say summarize summarise print send
    reply answer continue proceed retry rerun re-run""".split()
)

_GREETINGS = (
    "hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening", "good to meet you",
    "nice to meet you", "how can i help", "what can i help", "how are you", "thanks", "thank you",
    "you're welcome", "bye", "goodbye", "see you", "welcome",
)

# Assistant narration about what it is doing, not what is true.
_NARRATION_LEADS = (
    "let me", "i'll", "i will", "i'm going to", "i am going to", "now i", "next i", "first i", "i've",
    "i have", "i just", "here's", "here is", "sure", "certainly", "absolutely", "of course", "got it",
    "understood", "on it", "done", "running", "checking", "looking", "working on", "starting",
    "confirmed against", "as requested", "great", "perfect", "sounds good",
)

_MIN_STATEMENT_WORDS = 3

# Secrets: never stored, regardless of anything else the text says.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),  # OpenAI / Anthropic / OpenRouter style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # GitHub tokens
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(postgres|mysql|mongodb|redis|amqp)://[^\s:@]+:[^\s@]+@"),  # creds in URLs
)

_TOOL_OUTPUT_LEAD = re.compile(r"^\s*Tool\s+\S+\s+(result|failed|output|error)\s*:", re.IGNORECASE)
_MARKUP_TAG = re.compile(r"^\s*<[a-zA-Z][\w-]*(?:\s[^>]*)?>")
_JSON_LEAD = re.compile(r"^\s*[\[{]\s*[\"\[{]")
_CODE_HINTS = re.compile(
    r"(^\s*(def |class |import |from \S+ import |#include|function |const |let |var |SELECT |INSERT )"
    r"|Traceback \(most recent call last\)|^\s*File \"[^\"]+\", line \d+|\bat [\w.$<>]+\([\w.]+:\d+\)"
    r"|^\s*\$ |^\s*>>> |^diff --git|^@@ )",
    re.MULTILINE,
)
_URL_OR_PATH_ONLY = re.compile(r"^\s*(?:https?://\S+|(?:/|\./|~/)\S+)\s*$")

# Event types whose raw text is never a semantic fact: tool traffic and
# lifecycle noise. tool_failed is the one exception worth an LLM look
# (root causes/blockers), and only there.
_TOOL_EVENTS = frozenset({EventType.TOOL_STARTED, EventType.TOOL_COMPLETED, EventType.TASK_STARTED})
_ERROR_EVENTS = frozenset({EventType.TOOL_FAILED, EventType.TASK_FAILED})


# ---------------------------------------------------------------- predicates


def is_interrogative(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    first = text.split(None, 1)[0].lower().strip(",.:;")
    return first in _INTERROGATIVE_STARTS


def is_request(content: str) -> bool:
    raw = content.strip()
    text = raw.lower()
    if not text:
        return False
    if text.startswith(_REQUEST_LEADS):
        return True
    # Bare-verb openers only count when written as typed chat ("restart the
    # server"). A capitalized opener is far more often a subject noun that
    # happens to be a verb too ("Search changed its index…") — a fact.
    first = text.split(None, 1)[0].strip(",.:;!")
    return first in _IMPERATIVE_VERBS and raw[0].islower()


def is_conversational_filler(content: str) -> bool:
    return len(content.split()) < _MIN_STATEMENT_WORDS


def is_greeting(content: str) -> bool:
    text = content.strip().lower().rstrip("!.")
    if not text:
        return False
    # "Hi!", "Hello,", "Hey there" — punctuation after the greeting word
    # must not hide it.
    head = re.sub(r"[!.,;:]+", " ", text)
    if text in _GREETINGS or head.startswith(tuple(g + " " for g in _GREETINGS)):
        # "Hi Saman, good to meet you. How can I help you today?" — a
        # greeting that goes on to offer help is still a greeting.
        return len(text.split()) <= 16
    return False


def is_narration(content: str) -> bool:
    """Agent talking about its own process, not stating something durable."""
    text = content.strip().lower()
    return text.startswith(_NARRATION_LEADS)


def is_markup(content: str) -> bool:
    text = content.lstrip()
    return bool(_MARKUP_TAG.match(text)) or bool(_JSON_LEAD.match(text))


def is_tool_output(content: str) -> bool:
    return bool(_TOOL_OUTPUT_LEAD.match(content))


def looks_like_code_or_log(content: str) -> bool:
    if _CODE_HINTS.search(content):
        return True
    lines = [line for line in content.splitlines() if line.strip()]
    if len(lines) >= 6:
        # Mostly short, symbol-heavy lines = a dump, not prose.
        # "/" deliberately excluded: prose that mentions a few paths is prose.
        symbol_heavy = sum(1 for line in lines if sum(ch in "{}[]()<>=;|\\$#" for ch in line) >= 3)
        if symbol_heavy / len(lines) > 0.5:
            return True
    return False


def is_url_or_path_only(content: str) -> bool:
    return bool(_URL_OR_PATH_ONLY.match(content))


def contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in _SECRET_PATTERNS)


def redact_secrets(content: str) -> str:
    redacted = content
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def is_not_a_fact(content: str) -> bool:
    """Legacy single-flag view of the gate, for callers that only need
    yes/no (the rule-based evaluator)."""
    return not gate(content).admitted


# ---------------------------------------------------------------- gate


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str  # "ok" or the rejection category
    needs_extraction: bool = False  # admitted, but too long/mixed to store verbatim


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[]|[a-z])")


def sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]


def shape_rejection(sentence: str) -> Optional[str]:
    """Why one sentence, on its own, is not a fact — or None if it could be."""
    if is_greeting(sentence):
        return "greeting"
    if is_conversational_filler(sentence):
        return "filler"
    if is_interrogative(sentence):
        return "question"
    if is_request(sentence):
        return "directive"
    if is_narration(sentence):
        return "narration"
    return None


def gate(
    content: str,
    event_types: Iterable[EventType] = (),
    max_chars: int = DEFAULT_MAX_CANDIDATE_CHARS,
) -> AdmissionDecision:
    """Deterministic admission check.

    Hard never-store rules (secrets, tool traffic, markup, code) apply to
    the whole text. Shape rules (question, directive, greeting, narration,
    filler) apply per sentence: a single-sentence question is rejected; a
    paragraph that mixes a decision with a question ("…we chose RabbitMQ.
    Can you check the dashboard?") is admitted for LLM extraction, since
    the fact inside it is exactly what should be kept and the question is
    exactly what should not.
    """
    text = (content or "").strip()
    events = set(event_types)

    if not text:
        return AdmissionDecision(False, "empty")
    if contains_secret(text):
        return AdmissionDecision(False, "secret")
    if events & _TOOL_EVENTS or is_tool_output(text):
        return AdmissionDecision(False, "tool_output")
    if is_markup(text):
        return AdmissionDecision(False, "markup")
    if looks_like_code_or_log(text):
        return AdmissionDecision(False, "code_or_log")
    if is_url_or_path_only(text):
        return AdmissionDecision(False, "url_or_path_only")

    parts = sentences(text) or [text]
    verdicts = [shape_rejection(part) for part in parts]
    if len(parts) == 1:
        if verdicts[0] is not None:
            return AdmissionDecision(False, verdicts[0])
    elif all(v is not None for v in verdicts):
        return AdmissionDecision(False, verdicts[0])
    elif any(v is not None for v in verdicts):
        # Mixed: something declarative sits next to a question/directive.
        # Keep only through extraction, never verbatim.
        return AdmissionDecision(True, "ok", needs_extraction=True)

    if events & _ERROR_EVENTS:
        # Failures can hold a root cause worth remembering, but the raw
        # error text is not the memory — the LLM has to extract it.
        return AdmissionDecision(True, "ok", needs_extraction=True)
    if len(text) > max_chars:
        return AdmissionDecision(True, "ok", needs_extraction=True)
    return AdmissionDecision(True, "ok")


def event_types_of(experience) -> list[EventType]:
    return [event.event_type for event in getattr(experience, "events", ())]


def rejection_reasons() -> tuple[str, ...]:
    """Every reason `gate` can return, for docs/tests."""
    return (
        "empty", "secret", "tool_output", "markup", "code_or_log", "url_or_path_only",
        "filler", "greeting", "question", "directive", "narration",
    )


def explain(content: str, event_types: Iterable[EventType] = ()) -> Optional[str]:
    decision = gate(content, event_types)
    return None if decision.admitted else decision.reason
