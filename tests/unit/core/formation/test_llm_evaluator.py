import json

from core.formation.evaluator import LLMMemoryEvaluator
from domain.models.candidate import Candidate


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


def test_evaluate_fills_scores_from_llm_response():
    response = json.dumps(
        {
            "worth_remembering": True,
            "confidence": 0.9,
            "future_usefulness": 0.8,
            "durability": 0.7,
            "novelty": 0.6,
            "impact": 0.6,
            "specificity": 0.5,
            "reasoning": "Confirmed architecture decision.",
        }
    )
    evaluator = LLMMemoryEvaluator(ScriptedLLM(response))
    candidate = Candidate(content="Team uses Redis for caching")

    scored = evaluator.evaluate(candidate)

    assert scored.confidence == 0.9
    assert scored.future_usefulness == 0.8
    assert scored.durability == 0.7
    assert scored.novelty == 0.6
    assert scored.impact == 0.6
    assert scored.specificity == 0.5


def test_is_worth_remembering_applies_deterministic_threshold():
    low_scores = json.dumps(
        {"confidence": 0.1, "future_usefulness": 0.1, "durability": 0.1, "novelty": 0.1, "impact": 0.1, "specificity": 0.1}
    )
    evaluator = LLMMemoryEvaluator(ScriptedLLM(low_scores), threshold=0.5)
    scored = evaluator.evaluate(Candidate(content="casual chatter"))

    assert evaluator.is_worth_remembering(scored) is False
