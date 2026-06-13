"""
Tests for tools.parse_query (planning loop Step 2).

parse_query asks the LLM to extract {description, size, max_price} from a
natural-language query. Unit tests stub the `_chat` seam so they exercise the
JSON parsing / normalization / fallback logic deterministically and offline.
A live test is gated behind FITFINDR_LIVE_TESTS=1.
"""

import os

import pytest

import tools
from tools import parse_query


def _stub_chat(monkeypatch, response):
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature=0: response, raising=False)


def test_extracts_description_size_and_price(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "vintage graphic tee", "size": "M", "max_price": 30}')
    parsed = parse_query("vintage graphic tee under $30, size M")
    assert parsed["description"] == "vintage graphic tee"
    assert parsed["size"] == "M"
    assert parsed["max_price"] == 30.0
    assert isinstance(parsed["max_price"], float)


def test_optional_fields_become_none(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "red dress", "size": null, "max_price": null}')
    parsed = parse_query("a red dress")
    assert parsed["description"] == "red dress"
    assert parsed["size"] is None
    assert parsed["max_price"] is None


def test_price_given_as_string_is_coerced_to_float(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "jacket", "size": null, "max_price": "45"}')
    assert parse_query("a jacket under 45")["max_price"] == 45.0


def test_tolerates_json_wrapped_in_markdown_fence(monkeypatch):
    _stub_chat(monkeypatch, '```json\n{"description": "boots", "size": "8", "max_price": null}\n```')
    parsed = parse_query("boots size 8")
    assert parsed["description"] == "boots"
    assert parsed["size"] == "8"


def test_falls_back_to_raw_query_when_llm_returns_garbage(monkeypatch):
    _stub_chat(monkeypatch, "Sorry, I can't help with that.")
    parsed = parse_query("vintage tee")
    assert parsed["description"] == "vintage tee"   # fall back to the raw query
    assert parsed["size"] is None
    assert parsed["max_price"] is None


def test_always_returns_the_four_keys(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "hat"}')   # LLM omits the rest
    parsed = parse_query("a hat")
    assert set(parsed.keys()) == {"description", "size", "max_price", "category"}


def test_extracts_category(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "90s track jacket", "size": "M", "max_price": 30, "category": "outerwear"}')
    assert parse_query("90s track jacket, size M, under $30")["category"] == "outerwear"


def test_category_is_normalized_to_lowercase(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "boots", "size": "8", "max_price": null, "category": "Shoes"}')
    assert parse_query("boots size 8")["category"] == "shoes"


def test_invalid_category_becomes_none(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "dress", "size": null, "max_price": null, "category": "dresses"}')
    assert parse_query("a dress")["category"] is None


def test_missing_category_becomes_none(monkeypatch):
    _stub_chat(monkeypatch, '{"description": "hat"}')   # LLM omits category
    assert parse_query("a hat")["category"] is None


@pytest.mark.skipif(
    not os.environ.get("FITFINDR_LIVE_TESTS"),
    reason="set FITFINDR_LIVE_TESTS=1 to run live Groq calls",
)
def test_live_parses_real_query():
    parsed = parse_query("I'm looking for a vintage graphic tee under $30, size M. "
                         "I mostly wear baggy jeans and chunky sneakers.")
    assert "tee" in parsed["description"].lower()
    assert parsed["max_price"] == 30.0
    assert parsed["size"] and parsed["size"].lower() == "m"
    # the "what I wear" clause must NOT leak into the search description
    assert "jeans" not in parsed["description"].lower()
