"""Claude Code's real hook payload field names (hooks.md): UserPromptSubmit
carries `prompt`, PostToolUse carries `tool_response`, PostToolUseFailure
carries `error`. Legacy names remain accepted as fallbacks."""
from integrations.claude_code.event_mapper import (
    observation_text_for_prompt,
    observation_text_for_tool_failure,
    observation_text_for_tool_use,
)


def test_prompt_uses_official_prompt_field():
    assert observation_text_for_prompt({"prompt": " what db? "}) == "what db?"


def test_prompt_falls_back_to_legacy_user_prompt():
    assert observation_text_for_prompt({"user_prompt": "hi"}) == "hi"


def test_tool_use_uses_official_tool_response_field():
    event_type, text = observation_text_for_tool_use({"tool_name": "Bash", "tool_response": {"stdout": "ok"}})
    assert event_type == "tool_completed"
    assert "Bash" in text and "ok" in text


def test_tool_failure_uses_official_error_field():
    event_type, text = observation_text_for_tool_failure({"tool_name": "Bash", "error": "Exit code 1"})
    assert event_type == "tool_failed"
    assert "Exit code 1" in text


def test_system_payloads_are_not_observed():
    for prefix in ("<task-notification>", "<system-reminder>", "<local-command-caveat>", "<command-name>"):
        assert observation_text_for_prompt({"prompt": f"{prefix}\n<x>very long audit report</x>"}) == ""


def test_slash_commands_are_not_observed():
    assert observation_text_for_prompt({"prompt": "/clear"}) == ""
    assert observation_text_for_prompt({"prompt": "/model opus"}) == ""


def test_prompt_observation_is_capped_like_tool_output():
    long_prompt = "we decided " + "x" * 2000
    assert len(observation_text_for_prompt({"prompt": long_prompt})) == 500


def test_real_statements_still_pass():
    assert observation_text_for_prompt({"prompt": "We decided the billing worker uses RabbitMQ."}).startswith("We decided")
