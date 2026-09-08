import pytest

from core.json_utils import parse_json_response


def test_parses_plain_json():
    assert parse_json_response('{"action": "create"}') == {"action": "create"}


def test_strips_json_code_fence():
    raw = '```json\n{"action": "create"}\n```'
    assert parse_json_response(raw) == {"action": "create"}


def test_strips_plain_code_fence():
    raw = '```\n{"action": "ignore"}\n```'
    assert parse_json_response(raw) == {"action": "ignore"}


def test_parses_json_array():
    raw = '```json\n[{"content": "a"}, {"content": "b"}]\n```'
    assert parse_json_response(raw) == [{"content": "a"}, {"content": "b"}]


def test_raises_on_invalid_json():
    with pytest.raises(Exception):
        parse_json_response("not json at all")


def test_repairs_missing_closing_quote_before_final_brace():
    raw = '{"worth_remembering": true, "reasoning": "lacks context, confirmation, or specificity.}'
    assert parse_json_response(raw) == {
        "worth_remembering": True,
        "reasoning": "lacks context, confirmation, or specificity.",
    }


def test_repairs_missing_closing_quote_before_final_bracket():
    raw = '["a", "b]'
    assert parse_json_response(raw) == ["a", "b"]
