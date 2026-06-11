"""
Tests for tools.suggest_outfit.

suggest_outfit calls an LLM, so the unit tests monkeypatch the `_chat` seam
(the network boundary) to stay fast and deterministic. They verify the prompt
the tool builds and the guarantees it makes about its return value. A live
test that actually hits Groq is gated behind FITFINDR_LIVE_TESTS=1.
"""

import os

import pytest

import tools
from tools import suggest_outfit
from utils.data_loader import load_listings, get_example_wardrobe, get_empty_wardrobe


def _prompt_text(messages):
    return "\n".join(m["content"] for m in messages)


@pytest.fixture
def graphic_tee():
    return next(item for item in load_listings() if item["id"] == "lst_006")


@pytest.fixture
def capture_chat(monkeypatch):
    """Replace the LLM call with a stub that records the messages it receives."""
    captured = []

    def fake_chat(messages, temperature=0.7):
        captured.clear()
        captured.extend(messages)
        return "Pair it with your baggy jeans and chunky sneakers."

    monkeypatch.setattr(tools, "_chat", fake_chat, raising=False)
    return captured


def test_empty_wardrobe_requests_general_advice(graphic_tee, capture_chat):
    out = suggest_outfit(graphic_tee, get_empty_wardrobe())
    assert out.strip()  # never empty

    text = _prompt_text(capture_chat).lower()
    assert "general" in text                       # asks for general styling advice
    assert graphic_tee["title"].lower() in text    # still describes the new item


def test_filled_wardrobe_names_specific_pieces(graphic_tee, capture_chat):
    wardrobe = get_example_wardrobe()
    out = suggest_outfit(graphic_tee, wardrobe)
    assert out.strip()

    text = _prompt_text(capture_chat)
    assert graphic_tee["title"] in text
    for owned in wardrobe["items"]:
        assert owned["name"] in text, f"prompt should mention owned piece {owned['name']!r}"


def test_returns_stripped_llm_text(graphic_tee, monkeypatch):
    monkeypatch.setattr(
        tools, "_chat",
        lambda messages, temperature=0.7: "  Looks great with wide-leg jeans.  ",
        raising=False,
    )
    assert suggest_outfit(graphic_tee, get_example_wardrobe()) == "Looks great with wide-leg jeans."


def test_never_returns_empty_even_if_llm_blank(graphic_tee, monkeypatch):
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature=0.7: "   ", raising=False)
    out = suggest_outfit(graphic_tee, get_example_wardrobe())
    assert isinstance(out, str) and out.strip()


def test_handles_item_with_missing_optional_fields(capture_chat):
    sparse_item = {"title": "Mystery Surplus Jacket"}  # no category/colors/style_tags
    out = suggest_outfit(sparse_item, get_empty_wardrobe())
    assert out.strip()
    assert "Mystery Surplus Jacket" in _prompt_text(capture_chat)


@pytest.mark.skipif(
    not os.environ.get("FITFINDR_LIVE_TESTS"),
    reason="set FITFINDR_LIVE_TESTS=1 to run live Groq calls",
)
def test_live_returns_nonempty_for_both_paths(graphic_tee):
    assert suggest_outfit(graphic_tee, get_empty_wardrobe()).strip()
    assert suggest_outfit(graphic_tee, get_example_wardrobe()).strip()
