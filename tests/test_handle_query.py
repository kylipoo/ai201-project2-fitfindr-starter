"""
Tests for app.handle_query (the Gradio UI handler).

handle_query is thin glue: pick the wardrobe, call run_agent, and map the
session into the three output panels. Tests stub app.run_agent so they verify
the routing/formatting deterministically and offline. A live test is gated
behind FITFINDR_LIVE_TESTS=1.
"""

import os

import pytest

import app
from app import handle_query

CANNED_ITEM = {
    "id": "lst_006",
    "title": "Graphic Tee — 2003 Tour Bootleg Style",
    "price": 24.0,
    "platform": "depop",
    "size": "L",
    "condition": "good",
    "brand": None,
    "description": "Vintage-style bootleg tee with faded graphic.",
}


def _session(**overrides):
    session = {
        "query": "q",
        "parsed": {},
        "search_results": [CANNED_ITEM],
        "selected_item": CANNED_ITEM,
        "wardrobe": {"items": []},
        "outfit_suggestion": "OUTFIT TEXT",
        "fit_card": "CARD TEXT",
        "error": None,
        "match_quality": "exact",
    }
    session.update(overrides)
    return session


def test_empty_query_returns_message_without_calling_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "run_agent", lambda q, w: calls.append(1) or _session())

    listing, outfit, card = handle_query("", "Example wardrobe")
    assert listing.strip()          # a prompt-the-user message
    assert outfit == "" and card == ""
    assert not calls                # run_agent must not be called


def test_whitespace_query_returns_message_without_calling_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "run_agent", lambda q, w: calls.append(1) or _session())

    listing, outfit, card = handle_query("   \n ", "Example wardrobe")
    assert listing.strip()
    assert outfit == "" and card == ""
    assert not calls


def test_agent_error_shows_in_first_panel_only(monkeypatch):
    monkeypatch.setattr(app, "run_agent", lambda q, w: _session(
        error="No listings matched 'ballgown'.",
        selected_item=None, outfit_suggestion=None, fit_card=None,
    ))

    listing, outfit, card = handle_query("ballgown", "Example wardrobe")
    assert listing == "No listings matched 'ballgown'."
    assert outfit == "" and card == ""


def test_happy_path_formats_listing_and_passes_outfit_and_card(monkeypatch):
    monkeypatch.setattr(app, "run_agent", lambda q, w: _session())

    listing, outfit, card = handle_query("tee", "Example wardrobe")
    assert "Graphic Tee — 2003 Tour Bootleg Style" in listing   # title
    assert "24.00" in listing                                    # price
    assert "depop" in listing                                    # platform
    assert outfit == "OUTFIT TEXT"
    assert card == "CARD TEXT"


def test_example_choice_passes_populated_wardrobe(monkeypatch):
    seen = {}
    monkeypatch.setattr(app, "run_agent", lambda q, w: seen.update(wardrobe=w) or _session())

    handle_query("tee", "Example wardrobe")
    w = seen.get("wardrobe")
    assert w is not None and len(w["items"]) > 0


def test_empty_choice_passes_empty_wardrobe(monkeypatch):
    seen = {}
    monkeypatch.setattr(app, "run_agent", lambda q, w: seen.update(wardrobe=w) or _session())

    handle_query("tee", "Empty wardrobe (new user)")
    w = seen.get("wardrobe")
    assert w is not None and w["items"] == []


def test_fallback_prepends_caveat_to_listing(monkeypatch):
    monkeypatch.setattr(app, "run_agent", lambda q, w: _session(match_quality="fallback"))
    listing, outfit, card = handle_query("track jacket", "Example wardrobe")
    assert "couldn't find an exact match" in listing.lower()       # caveat shown
    assert "Graphic Tee — 2003 Tour Bootleg Style" in listing      # item still shown
    assert outfit == "OUTFIT TEXT" and card == "CARD TEXT"          # downstream unchanged


def test_exact_match_has_no_caveat(monkeypatch):
    monkeypatch.setattr(app, "run_agent", lambda q, w: _session(match_quality="exact"))
    listing, _, _ = handle_query("tee", "Example wardrobe")
    assert "couldn't find an exact match" not in listing.lower()


@pytest.mark.skipif(
    not os.environ.get("FITFINDR_LIVE_TESTS"),
    reason="set FITFINDR_LIVE_TESTS=1 to run live Groq calls",
)
def test_live_happy_path_fills_all_three_panels():
    listing, outfit, card = handle_query("vintage graphic tee under $30", "Example wardrobe")
    assert listing.strip() and outfit.strip() and card.strip()
