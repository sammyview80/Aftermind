import json

from integrations.claude_code.transcript import read_last_exchange


def _write_transcript(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries))


def test_read_last_exchange_extracts_plain_string_user_and_text_block_assistant(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "message": {"role": "user", "content": "We finished the SQLite integration."}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "internal, should be ignored"},
                        {"type": "text", "text": "Got it, noted."},
                    ],
                },
            },
        ],
    )

    result = read_last_exchange(str(transcript))

    assert result == "User: We finished the SQLite integration.\nAssistant: Got it, noted."


def test_read_last_exchange_uses_the_most_recent_user_and_assistant_entries(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "user", "message": {"role": "user", "content": "first message"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first reply"}]}},
            {"type": "user", "message": {"role": "user", "content": "second message"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "second reply"}]}},
        ],
    )

    result = read_last_exchange(str(transcript))

    assert "second message" in result
    assert "second reply" in result
    assert "first message" not in result


def test_read_last_exchange_skips_non_message_lines(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_transcript(
        transcript,
        [
            {"type": "system", "subtype": "init"},
            {"type": "attachment", "attachment": {"type": "hook_additional_context"}},
            {"type": "user", "message": {"role": "user", "content": "hello"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}},
        ],
    )

    assert read_last_exchange(str(transcript)) == "User: hello\nAssistant: hi"


def test_read_last_exchange_returns_empty_string_for_missing_file(tmp_path):
    assert read_last_exchange(str(tmp_path / "nonexistent.jsonl")) == ""


def test_read_last_exchange_returns_empty_string_for_none_path():
    assert read_last_exchange(None) == ""


def test_read_last_exchange_tolerates_malformed_json_lines(tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("not json\n" + json.dumps({"type": "user", "message": {"role": "user", "content": "ok"}}))

    assert "User: ok" in read_last_exchange(str(transcript))
