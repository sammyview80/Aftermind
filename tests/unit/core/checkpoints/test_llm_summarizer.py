import json

from core.checkpoints.summarizer import LLMCheckpointSummarizer
from domain.models.experience import Experience


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


def test_summarize_maps_llm_response_to_checkpoint_summary():
    response = json.dumps(
        {
            "goal": "Build the login flow",
            "completed": ["searched repo", "found auth module"],
            "current": "wiring session handling",
            "blocked_by": ["waiting on OAuth client secret"],
            "next_steps": ["add tests"],
        }
    )
    summarizer = LLMCheckpointSummarizer(ScriptedLLM(response))

    summary = summarizer.summarize(Experience())

    assert summary.goal == "Build the login flow"
    assert summary.completed == ("searched repo", "found auth module")
    assert summary.current == "wiring session handling"
    assert summary.blockers == ("waiting on OAuth client secret",)
    assert summary.next_steps == ("add tests",)


def test_build_prompt_includes_previous_goal():
    summarizer = LLMCheckpointSummarizer(ScriptedLLM("{}"))
    prompt = summarizer.build_prompt(Experience(), previous_goal="Build the login flow")
    assert "Build the login flow" in prompt


def test_build_prompt_prefixes_system_prompt_when_given():
    summarizer = LLMCheckpointSummarizer(ScriptedLLM("{}"), system_prompt="# Aftermind Checkpoint Summarizer")
    prompt = summarizer.build_prompt(Experience())
    assert prompt.startswith("# Aftermind Checkpoint Summarizer")
