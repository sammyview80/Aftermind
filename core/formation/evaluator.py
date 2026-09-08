from dataclasses import replace

from core.json_utils import parse_json_response
from domain.interfaces.llm_provider import LLMProvider
from domain.models.candidate import Candidate

# Words that mark a statement as tied to a fleeting moment rather than
# durable fact/preference/procedure.
_TRANSIENT_MARKERS = ("today", "right now", "currently just", "for now", "at the moment")

DEFAULT_WORTH_REMEMBERING_THRESHOLD = 0.5

# A question is a request for a fact, not a fact. Stored as memory it
# comes back as "Current facts: what database does Aftermind use" and
# even reaches the graph as `Aftermind -[USES_DATABASE]-> unknown`.
_INTERROGATIVE_STARTS = (
    "what", "why", "how", "when", "where", "who", "whom", "whose", "which",
    "is", "are", "am", "was", "were", "do", "does", "did", "can", "could",
    "should", "would", "will", "shall", "may", "might", "have", "has", "had",
    "isn't", "aren't", "don't", "doesn't", "didn't", "can't", "couldn't",
    "shouldn't", "wouldn't", "won't",
)
_MIN_STATEMENT_WORDS = 3

# A request to the agent ("also commit and push", "make it more layman",
# "restart the server") is a task, not a fact about the world. Tasks belong
# to checkpoints (goal / next steps), not to semantic memory — stored as
# facts they come back as nonsense "Current facts" on the next turn.
_REQUEST_LEADS = (
    "also", "please", "pls", "okay", "ok", "now", "next", "then", "just", "let's", "lets",
    "can you", "could you", "would you", "will you", "i want", "i need", "i'd like", "we need",
    "make sure", "go ahead", "try to", "don't", "do not",
)
_IMPERATIVE_VERBS = frozenset(
    """add build change check clean commit configure create debug delete deploy do document
    ensure explain fix generate give help implement install investigate keep list look make
    merge move open push read refactor remove rename restart run save search set show start
    stop test try update upgrade use verify write""".split()
)
_MARKUP_START = ("<", "[", "{")


def is_request(content: str) -> bool:
    raw = content.strip()
    text = raw.lower()
    if not text:
        return False
    if text.startswith(_REQUEST_LEADS):
        return True
    # Bare-verb openers only count when written as typed chat ("restart the
    # server", "commit and push"). A capitalized opener is far more often a
    # subject noun that happens to be a verb too ("Search changed its index
    # from X to Y") — a fact, not an order.
    first = text.split(None, 1)[0].strip(",.:;!")
    return first in _IMPERATIVE_VERBS and raw[0].islower()


def is_markup(content: str) -> bool:
    return content.lstrip().startswith(_MARKUP_START) and ">" in content or content.lstrip().startswith("{")


def is_not_a_fact(content: str) -> bool:
    """Deterministic gate applied before any score: questions, requests,
    filler and machine markup never become memories."""
    return is_interrogative(content) or is_request(content) or is_conversational_filler(content) or is_markup(content)


def is_interrogative(content: str) -> bool:
    text = content.strip()
    if not text:
        return False
    if text.endswith("?"):
        return True
    first = text.split(None, 1)[0].lower().strip(",.:;")
    return first in _INTERROGATIVE_STARTS


def is_conversational_filler(content: str) -> bool:
    """Too short to be a specific, durable statement ("ok", "i reloaded",
    "thanks that works")."""
    return len(content.split()) < _MIN_STATEMENT_WORDS


class MemoryEvaluator:
    """Scores a Candidate on the dimensions that matter for durable
    memory, and decides whether it clears the bar to proceed to
    reconciliation.

    Scoring here is evidence-independent — it only looks at the candidate
    itself. Whether the candidate duplicates, updates, or contradicts an
    existing memory is decided later, by the reconciler, once evidence has
    been retrieved.
    """

    def __init__(self, threshold: float = DEFAULT_WORTH_REMEMBERING_THRESHOLD) -> None:
        self.threshold = threshold

    def evaluate(self, candidate: Candidate) -> Candidate:
        """Return a copy of `candidate` with scoring fields filled in
        (existing non-zero scores are respected, not overwritten)."""
        content = candidate.content
        word_count = len(content.split())
        is_transient = any(marker in content.lower() for marker in _TRANSIENT_MARKERS)

        return replace(
            candidate,
            confidence=candidate.confidence or 0.8,
            future_usefulness=candidate.future_usefulness or 0.7,
            durability=candidate.durability or (0.3 if is_transient else 0.7),
            novelty=candidate.novelty or 0.6,
            impact=candidate.impact or 0.6,
            specificity=candidate.specificity or (0.8 if word_count > 6 else 0.4),
        )

    def overall_score(self, candidate: Candidate) -> float:
        dimensions = (
            candidate.confidence,
            candidate.future_usefulness,
            candidate.durability,
            candidate.novelty,
            candidate.impact,
            candidate.specificity,
        )
        return sum(dimensions) / len(dimensions)

    def is_worth_remembering(self, candidate: Candidate) -> bool:
        if is_not_a_fact(candidate.content):
            return False
        return self.overall_score(candidate) >= self.threshold


_EVALUATOR_PROMPT_TEMPLATE = """CANDIDATE:
{content}

Return a single JSON object:
{{"worth_remembering": true|false, "confidence": <0-1>, "future_usefulness": <0-1>, \
"durability": <0-1>, "novelty": <0-1>, "impact": <0-1>, "specificity": <0-1>, \
"memory_type": "semantic|episodic|procedural", "reasoning": "<one sentence>"}}

Respond with ONLY that JSON object — no prose, no markdown code fences.
"""


class LLMMemoryEvaluator:
    """LLM-backed scoring using providers/llm/prompts/evaluator.md as its
    instructions. The model proposes scores and a worth_remembering
    call; `is_worth_remembering` still applies the deterministic
    threshold as the final policy decision, per the prompt's own rule
    that the runtime makes that call."""

    def __init__(
        self, llm_provider: LLMProvider, system_prompt: str = "", threshold: float = DEFAULT_WORTH_REMEMBERING_THRESHOLD
    ) -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt
        self.threshold = threshold

    def build_prompt(self, candidate: Candidate) -> str:
        task = _EVALUATOR_PROMPT_TEMPLATE.format(content=candidate.content)
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def evaluate(self, candidate: Candidate) -> Candidate:
        raw = self._llm.complete(self.build_prompt(candidate))
        scored = parse_json_response(raw)

        return replace(
            candidate,
            confidence=float(scored.get("confidence", 0.0)),
            future_usefulness=float(scored.get("future_usefulness", 0.0)),
            durability=float(scored.get("durability", 0.0)),
            novelty=float(scored.get("novelty", 0.0)),
            impact=float(scored.get("impact", 0.0)),
            specificity=float(scored.get("specificity", 0.0)),
        )

    def overall_score(self, candidate: Candidate) -> float:
        return MemoryEvaluator.overall_score(self, candidate)

    def is_worth_remembering(self, candidate: Candidate) -> bool:
        # Deterministic policy applies before the model's scores: a
        # question or a request is never a fact, however confidently scored.
        if is_not_a_fact(candidate.content):
            return False
        return self.overall_score(candidate) >= self.threshold
