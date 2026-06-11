"""
Tests for tools.create_fit_card.

create_fit_card calls an LLM at high temperature, so unit tests stub the
`_chat` seam to stay fast and deterministic. They cover the empty-outfit guard
(which must NOT call the LLM), the prompt contents, the temperature, and the
return-value guarantees. A live test is gated behind FITFINDR_LIVE_TESTS=1.
"""

import os

import pytest

import tools
from tools import create_fit_card
from utils.data_loader import load_listings


def _prompt_text(messages):
    return "\n".join(m["content"] for m in messages)


@pytest.fixture
def graphic_tee():
    return next(item for item in load_listings() if item["id"] == "lst_006")


@pytest.fixture
def sample_outfit():
    return "Pair it with baggy jeans and chunky sneakers for a grunge look."


def test_empty_outfit_returns_error_without_calling_llm(graphic_tee, monkeypatch):
    called = []
    monkeypatch.setattr(tools, "_chat", lambda *a, **k: called.append(True) or "x", raising=False)

    out = create_fit_card("", graphic_tee)
    assert isinstance(out, str) and out.strip()   # a descriptive message, not empty
    assert not called                              # the LLM must not be called


def test_whitespace_outfit_returns_error_without_calling_llm(graphic_tee, monkeypatch):
    called = []
    monkeypatch.setattr(tools, "_chat", lambda *a, **k: called.append(True) or "x", raising=False)

    out = create_fit_card("   \n  ", graphic_tee)
    assert isinstance(out, str) and out.strip()
    assert not called


def test_prompt_includes_item_details_and_outfit(graphic_tee, sample_outfit, monkeypatch):
    captured = []

    def fake(messages, temperature=0.7):
        captured.clear()
        captured.extend(messages)
        return "caption"

    monkeypatch.setattr(tools, "_chat", fake, raising=False)
    create_fit_card(sample_outfit, graphic_tee)

    text = _prompt_text(captured)
    assert graphic_tee["title"] in text       # item name
    assert "24.00" in text                     # price
    assert graphic_tee["platform"] in text     # platform (depop)
    assert sample_outfit in text               # the styling content


def test_uses_high_temperature(graphic_tee, sample_outfit, monkeypatch):
    seen = {}

    def fake(messages, temperature=0.7):
        seen["temperature"] = temperature
        return "caption"

    monkeypatch.setattr(tools, "_chat", fake, raising=False)
    create_fit_card(sample_outfit, graphic_tee)
    assert seen["temperature"] >= 0.9          # hotter than suggest_outfit's 0.7


def test_returns_stripped_caption(graphic_tee, sample_outfit, monkeypatch):
    monkeypatch.setattr(
        tools, "_chat",
        lambda messages, temperature=0.7: "  thrifted gold off depop  ",
        raising=False,
    )
    assert create_fit_card(sample_outfit, graphic_tee) == "thrifted gold off depop"


def test_never_returns_empty_even_if_llm_blank(graphic_tee, sample_outfit, monkeypatch):
    monkeypatch.setattr(tools, "_chat", lambda messages, temperature=0.7: "   ", raising=False)
    out = create_fit_card(sample_outfit, graphic_tee)
    assert isinstance(out, str) and out.strip()


@pytest.mark.skipif(
    not os.environ.get("FITFINDR_LIVE_TESTS"),
    reason="set FITFINDR_LIVE_TESTS=1 to run live Groq calls",
)
def test_live_caption_is_nonempty(graphic_tee, sample_outfit):
    out = create_fit_card(sample_outfit, graphic_tee)
    assert out.strip()
