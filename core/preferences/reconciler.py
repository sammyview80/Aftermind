from typing import Any, Mapping, NamedTuple

from core.json_utils import parse_json_response
from domain.interfaces.llm_provider import LLMProvider
from domain.models.preference import Preference

_TASK_TEMPLATE = """Look across these recent user messages for response-style \
preference signals, given the user's current preference profile.

CURRENT PROFILE:
{profile_block}

RECENT MESSAGES:
{evidence_block}

Respond with a single JSON object:
{{"action": "ignore|update", "preferences": {{"<dimension>": {{...value...}}}}, \
"confidence": <0-1>, "reasoning": "<one sentence>"}}

- "ignore": nothing here changes the profile.
- "update": include only the dimensions that changed, e.g. \
{{"response_style.verbosity": {{"verbosity": "short"}}}}.

Respond with ONLY that JSON object — no prose, no markdown code fences.
"""


class PreferenceReconciliation(NamedTuple):
    action: str
    preferences: Mapping[str, Mapping[str, Any]]
    confidence: float
    reasoning: str


class LLMPreferenceReconciler:
    """Finds the subtler preference patterns plain regex heuristics miss
    — a repeated "what next?", never wanting a preamble, always asking
    for implementation over theory — by reading several recent messages
    together against the current profile. Deliberately *not* called on
    every turn (see `PreferenceManager.observe_text`'s evidence buffer):
    an LLM call per message would be slow and noisy for something this
    low-stakes."""

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, profile: tuple[Preference, ...], evidence: tuple[str, ...]) -> str:
        profile_block = (
            "\n".join(f"- {p.dimension}: {dict(p.value)}" for p in profile) if profile else "(empty — no preferences learned yet)"
        )
        evidence_block = "\n".join(f"{i}. {text}" for i, text in enumerate(evidence, start=1))
        task = _TASK_TEMPLATE.format(profile_block=profile_block, evidence_block=evidence_block)
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def reconcile(self, profile: tuple[Preference, ...], evidence: tuple[str, ...]) -> PreferenceReconciliation:
        prompt = self.build_prompt(profile, evidence)
        raw = self._llm.complete(prompt)
        parsed = parse_json_response(raw)

        return PreferenceReconciliation(
            action=parsed.get("action", "ignore"),
            preferences=parsed.get("preferences") or {},
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("reasoning", ""),
        )
