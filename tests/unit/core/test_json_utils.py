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
