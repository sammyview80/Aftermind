"""Golden set for the deterministic memory admission gate. Each REJECT
entry is a class of text that was actually observed being promoted to a
memory in live use before the gate existed."""
import json

import pytest

from core.formation import admission
from core.formation.admission import gate
from core.formation.admission_llm import LLMAdmission
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience

KEEP = (
    "We decided to use SQLite for storage, not JSON files, because we want querying later.",
    "The CLI command name is 'tsk', not 'tetsaman'.",
    "The todo priority levels are low/medium/high, stored as an integer 0-2 in SQLite.",
    "Automatic checkpointing is already committed & pushed (7c0865e) and verified live.",
    "tetsaman is a Python todo-list CLI app owned by saman.",
    "Billing used Redis before for its message queue.",
    "Search changed its search index from Elasticsearch to OpenSearch after a team decision.",
    "The client prefers dark layouts with black and gold accents.",
    "Saman Shrestha owns the Aftermind repository.",
    "Tests run with pytest from the .venv interpreter, excluding the live LLM test.",
)

REJECT = {
    "question": ("what database does Aftermind use", "What were we working on and what is next?", "is neo4j running?"),
    "directive": (
        "also commit and push",
        "restart the server",
        "okay add this to findings",
        "test again and tell me what happened",
        "please check the logs for errors",
        "i want to make sure hermes uses the existing key",
    ),
    "filler": ("say ok", "ok thanks", "yes"),
    "greeting": ("hi", "Hi Saman, good to meet you. How can I help you today?", "Hi! What can I help you with today?", "Hello there, how are you doing"),
    "narration": (
        "Let me check the repository first.",
        "I'll now run the test suite and report back.",
        "Confirmed against the actual repo — matches what the notes say.",
        "Done, all green.",
    ),
    "tool_output": (
        'Tool read_file result: {"content": "1|from typing import Any"}',
        "Tool Bash failed: Exit code 1",
    ),
    "markup": (
        '<cross-session-message from="uds:x">Four issues</cross-session-message>',
        '<task-notification><task-id>abc</task-id></task-notification>',
        '{"hook_event_name": "Stop", "cwd": "/tmp"}',
        '[{"memory_id": "x"}]',
    ),
    "code_or_log": (
        "def observe(self, experience):\n    return None",
        'Traceback (most recent call last):\n  File "x.py", line 1, in <module>\n    boom()',
        "diff --git a/x b/x\n@@ -1 +1 @@",
    ),
    "url_or_path_only": ("https://github.com/sammyview80/Aftermind", "/Volumes/SK/personal/aftermind/agent-memory"),
    "secret": (
        "The API key is sk-abcdefghijklmnopqrstuvwxyz123456 and the model is gpt-4o",
        "export GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "postgres://app:supersecret@db.internal:5432/aftermind is the DSN",
        "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop",
        "password = hunter2hunter2",
    ),
}


@pytest.mark.parametrize("text", KEEP)
def test_keep_set_is_admitted(text):
    decision = gate(text)
    assert decision.admitted, f"wrongly rejected ({decision.reason}): {text}"
    assert not decision.needs_extraction


@pytest.mark.parametrize("reason,text", [(r, t) for r, texts in REJECT.items() for t in texts])
def test_reject_set_is_rejected_with_the_right_reason(reason, text):
    decision = gate(text)
    assert not decision.admitted, f"wrongly kept: {text}"
    assert decision.reason == reason


def test_tool_events_are_rejected_even_when_text_looks_like_prose():
    assert gate("The repository has 48 files", [EventType.TOOL_COMPLETED]).reason == "tool_output"


def test_error_events_and_long_text_need_llm_extraction():
    failed = gate("The migration failed because the users table already has a status column.", [EventType.TOOL_FAILED])
    assert failed.admitted and failed.needs_extraction
    long = gate("We decided many things. " * 40)
    assert long.admitted and long.needs_extraction


def test_mixed_paragraph_is_admitted_for_extraction_not_verbatim():
    mixed = (
        "Codex here: quick recap. We decided on RabbitMQ instead of Redis for the billing worker because "
        "we need durable delivery. The deploy is running right now. Can you check the dashboard later?"
    )
    decision = gate(mixed)
    assert decision.admitted and decision.needs_extraction

    all_questions = "What did we decide? Is the deploy done? Who owns billing?"
    assert gate(all_questions).reason == "question"

    declarative_pair = "The billing worker uses RabbitMQ. Failed messages are retried three times."
    assert gate(declarative_pair) == admission.AdmissionDecision(True, "ok", False)

    # Narration followed by a fact: the fact is extractable, the narration is not stored.
    assert gate("Done. The migration file is written.") == admission.AdmissionDecision(True, "ok", True)


def test_secret_beats_everything_else():
    assert gate("also use sk-abcdefghijklmnopqrstuvwxyz123456 please").reason == "secret"
    assert admission.redact_secrets("key sk-abcdefghijklmnopqrstuvwxyz123456 done") == "key [REDACTED] done"


def test_every_documented_reason_is_reachable():
    reachable = {gate(t).reason for texts in REJECT.values() for t in texts} | {"empty"}
    assert reachable == set(admission.rejection_reasons())


# ---------------------------------------------------------------- LLM stage


class ScriptedAdmissionLLM:
    def __init__(self, proposals):
        self.proposals = proposals
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.proposals)


def _experience(text, event_type=EventType.AGENT_MESSAGE):
    return Experience(events=[Event(event_type=event_type)], output=text)


def test_llm_admission_extracts_atomic_statements_and_regates_them():
    llm = ScriptedAdmissionLLM(
        [
            {"content": "The billing worker uses RabbitMQ.", "memory_type": "semantic", "entities": ["billing worker", "RabbitMQ"], "relationships": ["billing worker uses RabbitMQ"], "usefulness": 0.9, "durability": 0.8, "confidence": 0.9, "user_confirmed": True},
            {"content": "what should we do next?", "usefulness": 0.9, "durability": 0.9},  # question: gate drops it
            {"content": "The build is currently running.", "usefulness": 0.9, "durability": 0.1},  # below score bar
            {"content": "Use sk-abcdefghijklmnopqrstuvwxyz123456 as the key", "usefulness": 1, "durability": 1},  # secret
            "not a dict",
        ]
    )
    stage = LLMAdmission(llm, system_prompt="ADMISSION SYSTEM", min_score=0.5)

    candidates = stage.extract(_experience("Codex here: after discussion the billing worker uses RabbitMQ; what should we do next?"))

    assert [c.content for c in candidates] == ["The billing worker uses RabbitMQ."]
    c = candidates[0]
    assert c.entities == ("billing worker", "RabbitMQ")
    assert c.future_usefulness == 0.9 and c.durability == 0.8 and c.confidence == 0.9
    assert c.user_confirmed is True
    assert c.metadata["admission"] == "llm"
    assert llm.prompts[0].startswith("ADMISSION SYSTEM")
    assert "speaker: assistant" in llm.prompts[0]


def test_llm_admission_redacts_secrets_before_the_model_sees_them():
    llm = ScriptedAdmissionLLM([])
    LLMAdmission(llm).extract(_experience("token sk-abcdefghijklmnopqrstuvwxyz123456 is set", EventType.USER_MESSAGE))
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in llm.prompts[0]
    assert "[REDACTED]" in llm.prompts[0]
    assert "speaker: user" in llm.prompts[0]


def test_llm_admission_tolerates_object_or_garbage_responses():
    assert LLMAdmission(ScriptedAdmissionLLM({"memories": []})).extract(_experience("x y z")) == []
    assert LLMAdmission(ScriptedAdmissionLLM("nonsense")).extract(_experience("x y z")) == []
