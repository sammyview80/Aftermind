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


def test_agent_self_framing_is_stripped_from_candidates():
    from core.formation.candidate_extractor import CandidateExtractor, strip_agent_framing
    from domain.models.experience import Experience

    assert strip_agent_framing("Codex here: we decided the billing worker uses RabbitMQ.") == "We decided the billing worker uses RabbitMQ."
    assert strip_agent_framing("Hermes here — we also decided to use SQLite.") == "We also decided to use SQLite."
    assert strip_agent_framing("Claude Code here again, the migration is done.") == "The migration is done."
    assert strip_agent_framing("As Codex, I recommend PostgreSQL for storage.") == "I recommend PostgreSQL for storage."
    # Plain statements and legitimate uses of "here" are untouched.
    assert strip_agent_framing("The config lives here: ./aftermind.db") == "The config lives here: ./aftermind.db"
    assert strip_agent_framing("We decided the billing worker uses RabbitMQ.") == "We decided the billing worker uses RabbitMQ."

    [candidate] = CandidateExtractor().extract(Experience(output="Codex here: we decided the billing worker uses RabbitMQ."))
    assert candidate.content == "We decided the billing worker uses RabbitMQ."


def test_requests_and_markup_are_not_facts():
    from core.formation.evaluator import is_not_a_fact, is_request

    for text in (
        "also commit and push",
        "restart the server",
        "also make it more layman interface and ux",
        "please check the logs for errors in the worker",
        "i want to make sure hermes uses the existing key",
        "Make sure to ask the user which key to use",
        "let's add tracing to the recall path",
    ):
        assert is_request(text), text
    # Capitalized subject nouns that double as verbs are facts, not orders.
    assert not is_request("Search changed its search index from Elasticsearch to OpenSearch.")
    assert not is_request("Build times dropped to 4 minutes after the cache change.")
    assert is_not_a_fact('<cross-session-message from="x">hello</cross-session-message>')
    assert is_not_a_fact("{\"hook_event_name\": \"Stop\"}")

    for text in (
        "We decided the billing worker uses RabbitMQ.",
        "Aftermind uses SQLite for local persistence.",
        "The client prefers dark layouts.",
        "Tests run with pytest from the .venv interpreter.",
    ):
        assert not is_not_a_fact(text), text


def test_live_keep_reject_pairs_from_claude_code_sessions():
    """Real prompts observed through the Claude Code hooks (2026-09-09):
    declarative project facts must survive, directives to the assistant
    about tooling/session mechanics must not."""
    from core.formation.evaluator import is_not_a_fact

    keep = (
        "We decided to use SQLite for storage, not JSON files, because we want querying later.",
        "The CLI command name is 'tsk', not 'tetsaman'.",
        "The todo priority levels are low/medium/high, stored as an integer 0-2 in SQLite.",
        "Automatic checkpointing is already committed & pushed (7c0865e) and verified live.",
        "tetsaman is a Python todo-list CLI app owned by saman.",
    )
    reject = (
        "also commit and push",
        "restart the server",
        "say ok",
        "okay add this to findings",
        "also make it more layman interface and ux, use /ui-ux-pro-max",
        "test again and tell me what happened",
        "add these issues to the other claude running session and tell it to fix it",
        "okay create new project it tetsaman and start now",
        "What were we working on and what is next?",
    )
    for text in keep:
        assert not is_not_a_fact(text), f"wrongly rejected: {text}"
    for text in reject:
        assert is_not_a_fact(text), f"wrongly kept: {text}"
