from domain.models.checkpoint import Checkpoint
from integrations.hermes.checkpoint_adapter import from_hermes_checkpoint, to_hermes_checkpoint


def test_to_hermes_checkpoint_renames_blockers_to_blocked_by():
    checkpoint = Checkpoint(
        goal="Build login flow",
        completed=["searched repo"],
        current="wiring session handling",
        blockers=["waiting on OAuth client secret"],
        next_steps=["add tests"],
        version=2,
    )

    data = to_hermes_checkpoint(checkpoint)

    assert data == {
        "goal": "Build login flow",
        "completed": ["searched repo"],
        "current": "wiring session handling",
        "blocked_by": ["waiting on OAuth client secret"],
        "next_steps": ["add tests"],
        "version": 2,
    }


def test_from_hermes_checkpoint_maps_blocked_by_to_blockers():
    summary = from_hermes_checkpoint(
        {
            "goal": "Build login flow",
            "completed": ["searched repo"],
            "current": "wiring session handling",
            "blocked_by": ["waiting on OAuth client secret"],
            "next_steps": ["add tests"],
        }
    )

    assert summary.goal == "Build login flow"
    assert summary.completed == ("searched repo",)
    assert summary.blockers == ("waiting on OAuth client secret",)
    assert summary.next_steps == ("add tests",)


def test_from_hermes_checkpoint_handles_missing_fields():
    summary = from_hermes_checkpoint({})
    assert summary.goal == ""
    assert summary.completed == ()
    assert summary.blockers == ()
