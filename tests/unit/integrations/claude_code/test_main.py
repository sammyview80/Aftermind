import json
import subprocess
import sys


def _run(payload: dict, cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "integrations.claude_code"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )


def test_unknown_event_exits_cleanly_with_no_output(tmp_path):
    result = _run({"hook_event_name": "SomeUnknownEvent"}, cwd=".")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_malformed_stdin_exits_cleanly():
    result = subprocess.run(
        [sys.executable, "-m", "integrations.claude_code"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_a_failing_handler_never_raises_out_of_main(monkeypatch):
    # UserPromptSubmit will try (and fail) to reach a real Aftermind
    # server at the default URL in this sandbox — main() must still
    # exit 0 rather than propagate any exception.
    result = subprocess.run(
        [sys.executable, "-m", "integrations.claude_code"],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "user_prompt": "hi"}),
        capture_output=True,
        text=True,
        env={"AFTERMIND_URL": "http://127.0.0.1:1", "AFTERMIND_RECALL_TIMEOUT": "1", "PATH": "/usr/bin:/bin"},
        timeout=10,
    )
    assert result.returncode == 0
