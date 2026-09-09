import json

from core.preferences.reconciler import LLMPreferenceReconciler
from domain.models.preference import Preference


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.last_prompt = None

    def complete(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


def test_reconcile_parses_update_action():
    llm = FakeLLM(
        json.dumps(
            {
                "action": "update",
                "preferences": {"response_style.directness": {"directness": "high"}},
                "confidence": 0.8,
                "reasoning": "repeated what-next requests",
            }
        )
    )
    result = LLMPreferenceReconciler(llm).reconcile((), ("what next?", "what next?", "just steps"))

    assert result.action == "update"
    assert result.preferences == {"response_style.directness": {"directness": "high"}}
    assert result.confidence == 0.8


def test_reconcile_parses_ignore_action():
    llm = FakeLLM(json.dumps({"action": "ignore", "preferences": {}, "confidence": 0.1, "reasoning": "no pattern"}))
    result = LLMPreferenceReconciler(llm).reconcile((), ("hello", "thanks"))
    assert result.action == "ignore"
    assert result.preferences == {}


def test_build_prompt_includes_current_profile_and_evidence():
    profile = (Preference(dimension="response_style.verbosity", value={"verbosity": "short"}),)
    reconciler = LLMPreferenceReconciler(FakeLLM("{}"))

    prompt = reconciler.build_prompt(profile, ("what next?",))

    assert "response_style.verbosity" in prompt
    assert "what next?" in prompt


def test_build_prompt_handles_empty_profile():
    reconciler = LLMPreferenceReconciler(FakeLLM("{}"))
    prompt = reconciler.build_prompt((), ("hi",))
    assert "no preferences learned yet" in prompt
