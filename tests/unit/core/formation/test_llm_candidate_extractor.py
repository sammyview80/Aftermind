import json

from core.formation.candidate_extractor import LLMCandidateExtractor
from domain.enums.event_type import EventType
from domain.enums.memory_type import MemoryType
from domain.models.event import Event
from domain.models.experience import Experience


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_extract_maps_llm_proposals_to_candidates():
    response = json.dumps(
        [
            {
                "content": "Team uses Redis for caching",
                "memory_type": "semantic",
                "entities": ["team", "redis"],
                "relationships": ["team uses redis"],
                "user_confirmed": True,
                "confidence": 0.9,
            }
        ]
    )
    llm = ScriptedLLM(response)
    experience = Experience(
        experience_id="exp1",
        events=[Event(event_id="e1", event_type=EventType.AGENT_MESSAGE)],
        output="We use Redis for caching.",
    )

    candidates = LLMCandidateExtractor(llm).extract(experience)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.experience_id == "exp1"
    assert candidate.content == "Team uses Redis for caching"
    assert candidate.memory_type == MemoryType.SEMANTIC
    assert candidate.entities == ("team", "redis")
    assert candidate.relationships == ("team uses redis",)
    assert candidate.user_confirmed is True
    assert candidate.confidence == 0.9
    assert candidate.source_event_ids == ("e1",)


def test_extract_returns_empty_list_when_llm_finds_nothing_meaningful():
    llm = ScriptedLLM("[]")
    candidates = LLMCandidateExtractor(llm).extract(Experience(output="okay thanks"))
    assert candidates == []


def test_build_prompt_prefixes_system_prompt_when_given():
    llm = ScriptedLLM("[]")
    extractor = LLMCandidateExtractor(llm, system_prompt="# Aftermind Candidate Extractor")
    prompt = extractor.build_prompt(Experience())
    assert prompt.startswith("# Aftermind Candidate Extractor")
