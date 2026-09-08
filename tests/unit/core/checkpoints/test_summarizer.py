from core.checkpoints.summarizer import CheckpointSummarizer
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience


def test_summarizes_full_lifecycle_experience():
    experience = Experience(
        input="Build the login flow",
        output="Login flow implemented",
        events=[
            Event(event_type=EventType.USER_MESSAGE, payload={"text": "Build the login flow"}),
            Event(event_type=EventType.TOOL_STARTED, payload={"tool": "repo_search"}),
            Event(event_type=EventType.TOOL_COMPLETED, payload={"result": "found auth module"}),
            Event(event_type=EventType.TOOL_FAILED, payload={"error": "OAuth client secret missing"}),
            Event(event_type=EventType.AGENT_MESSAGE, payload={"text": "Login flow implemented"}),
            Event(event_type=EventType.TASK_COMPLETED, payload={"result": "tests passed"}),
        ],
    )

    summary = CheckpointSummarizer().summarize(experience)

    assert summary.goal == "Build the login flow"
    assert summary.completed == ("found auth module", "tests passed")
    assert summary.current == "Login flow implemented"
    assert summary.blockers == ("OAuth client secret missing",)
    assert summary.next_steps == ()


def test_falls_back_to_experience_input_and_output_without_message_events():
    experience = Experience(
        input="Build the login flow",
        output="Login flow implemented",
        events=[Event(event_type=EventType.TASK_COMPLETED, payload={"result": "tests passed"})],
    )

    summary = CheckpointSummarizer().summarize(experience)

    assert summary.goal == "Build the login flow"
    assert summary.current == "Login flow implemented"


def test_reads_next_steps_from_experience_metadata():
    experience = Experience(metadata={"next_steps": ["add tests", "wire up refresh tokens"]})

    summary = CheckpointSummarizer().summarize(experience)

    assert summary.next_steps == ("add tests", "wire up refresh tokens")


def test_empty_experience_produces_empty_summary():
    summary = CheckpointSummarizer().summarize(Experience())

    assert summary.goal == ""
    assert summary.completed == ()
    assert summary.current == ""
    assert summary.blockers == ()
    assert summary.next_steps == ()
