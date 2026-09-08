"""Questions and conversational filler are not facts: the evaluator must
reject them before reconciliation regardless of how the dimensions score."""
import json

from core.formation.evaluator import LLMMemoryEvaluator, MemoryEvaluator, is_conversational_filler, is_interrogative
from domain.models.candidate import Candidate


def test_interrogatives_are_detected():
    for text in (
        "what database does Aftermind use",
        "What is tetsaman and what is the next step?",
        "i reloaded nowt it works?",
        "Does the billing worker use RabbitMQ",
        "How do we deploy this",
    ):
        assert is_interrogative(text), text


def test_statements_are_not_interrogative():
    for text in (
        "Aftermind uses PostgreSQL for canonical storage",
        "We decided the billing worker uses RabbitMQ.",
        "The client prefers dark layouts",
    ):
        assert not is_interrogative(text), text


def test_filler_is_detected():
    assert is_conversational_filler("ok thanks")
    assert is_conversational_filler("i reloaded")
    assert not is_conversational_filler("Team uses PostgreSQL for storage")


def test_rule_based_evaluator_rejects_questions_even_when_scores_are_high():
    evaluator = MemoryEvaluator()
    question = evaluator.evaluate(Candidate(content="What database does Aftermind use for canonical storage?"))
    statement = evaluator.evaluate(Candidate(content="Aftermind uses PostgreSQL for canonical storage"))

    assert evaluator.overall_score(question) >= evaluator.threshold  # scores alone would let it through
    assert evaluator.is_worth_remembering(question) is False
    assert evaluator.is_worth_remembering(statement) is True


def test_llm_evaluator_applies_the_same_policy():
    class ConfidentLLM:
        def complete(self, prompt):
            return json.dumps(
                {
                    "worth_remembering": True,
                    "confidence": 0.95,
                    "future_usefulness": 0.9,
                    "durability": 0.9,
                    "novelty": 0.9,
                    "impact": 0.9,
                    "specificity": 0.9,
                }
            )

    evaluator = LLMMemoryEvaluator(ConfidentLLM())
    scored = evaluator.evaluate(Candidate(content="what is tetsaman and what is the next step?"))
    assert evaluator.is_worth_remembering(scored) is False
