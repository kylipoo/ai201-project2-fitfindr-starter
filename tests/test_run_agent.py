"""
Tests for agent.run_agent (the planning loop).

These test the ORCHESTRATION, not the tools themselves: the four tool calls
(parse_query, search_listings, suggest_outfit, create_fit_card) are stubbed in
the agent's namespace so the 7-step flow and its early-exit branch are verified
deterministically and offline. A live end-to-end test is gated behind
FITFINDR_LIVE_TESTS=1.
"""

import os

import pytest

import agent
from agent import run_agent

ITEM = {"id": "lst_x", "title": "Faded Tee", "price": 22.0, "platform": "depop"}


def _stub_tools(monkeypatch, *, parsed=None, results=None, outfit="OUTFIT TEXT", card="CARD TEXT"):
    parsed = parsed or {"description": "tee", "size": None, "max_price": None}
    results = [ITEM] if results is None else results
    monkeypatch.setattr(agent, "parse_query", lambda query: parsed)
    monkeypatch.setattr(agent, "search_listings", lambda desc, size=None, max_price=None: results)
    monkeypatch.setattr(agent, "suggest_outfit", lambda new_item, wardrobe: outfit)
    monkeypatch.setattr(agent, "create_fit_card", lambda outfit, new_item: card)


def test_happy_path_populates_whole_session(monkeypatch):
    _stub_tools(monkeypatch)
    session = run_agent("vintage tee", {"items": []})

    assert session["error"] is None
    assert session["selected_item"] == ITEM
    assert session["outfit_suggestion"] == "OUTFIT TEXT"
    assert session["fit_card"] == "CARD TEXT"
    assert session["parsed"]["description"] == "tee"


def test_no_results_sets_error_and_skips_downstream(monkeypatch):
    calls = {"suggest": 0, "card": 0}

    monkeypatch.setattr(agent, "parse_query",
                        lambda query: {"description": "ballgown", "size": "XXS", "max_price": 5.0})
    monkeypatch.setattr(agent, "search_listings", lambda desc, size=None, max_price=None: [])

    def boom_suggest(*a, **k):
        calls["suggest"] += 1
        return "x"

    def boom_card(*a, **k):
        calls["card"] += 1
        return "x"

    monkeypatch.setattr(agent, "suggest_outfit", boom_suggest)
    monkeypatch.setattr(agent, "create_fit_card", boom_card)

    session = run_agent("designer ballgown size XXS under $5", {"items": []})

    assert session["error"]                       # a helpful error message is set
    assert session["outfit_suggestion"] is None   # downstream steps did not run
    assert session["fit_card"] is None
    assert calls["suggest"] == 0                   # suggest_outfit was NOT called
    assert calls["card"] == 0                      # create_fit_card was NOT called


def test_selects_top_ranked_result(monkeypatch):
    first = {"id": "a", "title": "First", "price": 10.0, "platform": "depop"}
    second = {"id": "b", "title": "Second", "price": 12.0, "platform": "depop"}
    _stub_tools(monkeypatch, results=[first, second])

    session = run_agent("tee", {"items": []})
    assert session["selected_item"] == first


def test_threads_outfit_and_item_into_create_fit_card(monkeypatch):
    seen = {}
    _stub_tools(monkeypatch, outfit="MY_OUTFIT")

    def capture(outfit, new_item):
        seen["outfit"] = outfit
        seen["item"] = new_item
        return "CARD"

    monkeypatch.setattr(agent, "create_fit_card", capture)

    run_agent("tee", {"items": []})
    assert seen["outfit"] == "MY_OUTFIT"     # outfit_suggestion flows into the card
    assert seen["item"] == ITEM              # selected_item flows into the card


def test_error_message_mentions_query_constraints(monkeypatch):
    monkeypatch.setattr(agent, "parse_query",
                        lambda query: {"description": "ballgown", "size": "XXS", "max_price": 5.0})
    monkeypatch.setattr(agent, "search_listings", lambda desc, size=None, max_price=None: [])

    session = run_agent("designer ballgown size XXS under $5", {"items": []})
    msg = session["error"].lower()
    assert "ballgown" in msg          # names what was searched
    assert "5" in msg                 # references the price ceiling


@pytest.mark.skipif(
    not os.environ.get("FITFINDR_LIVE_TESTS"),
    reason="set FITFINDR_LIVE_TESTS=1 to run live Groq calls",
)
def test_live_end_to_end_happy_and_no_results():
    from utils.data_loader import get_example_wardrobe

    ok = run_agent("vintage graphic tee under $30", get_example_wardrobe())
    assert ok["error"] is None
    assert ok["selected_item"] and ok["outfit_suggestion"].strip() and ok["fit_card"].strip()

    none = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    assert none["error"]
    assert none["outfit_suggestion"] is None and none["fit_card"] is None
