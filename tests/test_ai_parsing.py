from types import SimpleNamespace

import pytest

from estimator import ai


def text(t):
    return SimpleNamespace(type="text", text=t)


def test_extract_json_variants():
    assert ai.extract_json('{"a": 1}') == {"a": 1}
    assert ai.extract_json('Here you go:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert ai.extract_json('blah {"a": 3} blah') == {"a": 3}
    with pytest.raises(ValueError):
        ai.extract_json("no json here")


def test_final_json_prefers_last_block_and_joins_split_blocks():
    content = [text("Let me search for prices."), SimpleNamespace(type="server_tool_use"),
               text('{"job_name": "x", '), text('"line_items": []}')]
    assert ai._final_json(content) == {"job_name": "x", "line_items": []}


def test_final_json_raises_when_missing():
    with pytest.raises(ai.EstimateError):
        ai._final_json([text("sorry")])


def test_tools_include_location_only_when_set():
    tools = ai._tools({"city": "Austin", "state": "TX"})
    assert tools[0]["user_location"]["city"] == "Austin"
    assert "user_location" not in ai._tools({})[0]


def test_normalize_fills_and_coerces():
    from estimator import schemas
    data = ai.normalize({"quote_total": "$1,234.50", "line_items": [{"item": "x", "quantity": "3",
                         "is_local": "yes", "confidence": "very"}]}, schemas.QUOTE_CHECK)
    assert data["quote_total"] == 1234.5 and data["warnings"] == [] and data["job_name"] == ""
    item = data["line_items"][0]
    assert item["quantity"] == 3.0 and item["unit_price"] == 0.0 and item["is_local"] is True
    assert item["confidence"] == "low" and item["source_url"] == ""


def test_manual_prompt_contains_schema_and_location():
    p = ai.manual_prompt({"city": "Austin", "state": "TX", "zip": "78701"}, "REQUEST", "estimate")
    assert "78701" in p and "REQUEST" in p and "```json" in p and '"questions_to_confirm"' in p
