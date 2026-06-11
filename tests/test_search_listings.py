"""
Tests for tools.search_listings.

search_listings is the one deterministic tool (no LLM), so its behavior is
pinned down here against the real data/listings.json dataset.
"""

from tools import search_listings
from utils.data_loader import load_listings

LISTING_KEYS = {
    "id", "title", "description", "category", "style_tags",
    "size", "condition", "price", "colors", "brand", "platform",
}


def _ids(results):
    return [r["id"] for r in results]


def test_finds_graphic_tees_and_ranks_more_relevant_first():
    # "vintage graphic tee" has 3 keywords. Items matching all 3 must rank
    # above an item matching 2, which must rank above an item matching 1.
    results = search_listings("vintage graphic tee")
    ids = _ids(results)

    # strong (3-keyword) matches: lst_002, lst_006, lst_033
    assert results[0]["id"] in {"lst_002", "lst_006", "lst_033"}

    # lst_006 (vintage+graphic+tee) > lst_015 (vintage+graphic) > lst_001 (vintage)
    assert ids.index("lst_006") < ids.index("lst_015") < ids.index("lst_001")


def test_filters_by_max_price_inclusive():
    results = search_listings("vintage", max_price=20.0)

    assert results, "expected some vintage items at or under $20"
    assert all(r["price"] <= 20.0 for r in results)
    # lst_012 is exactly $20.00 — the boundary must be included.
    assert "lst_012" in _ids(results)
    # lst_001 is $38.00 — must be excluded.
    assert "lst_001" not in _ids(results)


def test_filters_by_size_case_insensitive():
    # lowercase "m" must still match sizes like "S/M", "M", "M/L".
    results = search_listings("vintage", size="m")

    assert results, "expected vintage items in a medium-ish size"
    for r in results:
        size_tokens = set(r["size"].lower().replace("/", " ").split())
        assert "m" in size_tokens, f"{r['id']} size {r['size']!r} should not match 'm'"
    # lst_006 is size "L" — must be excluded by the size filter.
    assert "lst_006" not in _ids(results)


def test_no_keyword_match_returns_empty_list():
    assert search_listings("designer ballgown") == []


def test_impossible_price_returns_empty_list():
    # Plenty of vintage items exist, but none under $5.
    assert search_listings("vintage", max_price=5.0) == []


def test_drops_zero_score_listings():
    # "denim" should only return denim-related items; a knit cardigan must not leak in.
    results = search_listings("denim")
    ids = _ids(results)

    assert results
    assert "lst_001" in ids          # Vintage Levi's 501 Jeans (denim tag)
    assert "lst_008" not in ids      # Knit Cardigan — no denim keyword


def test_returns_full_listing_dicts():
    results = search_listings("vintage")
    assert results
    assert set(results[0].keys()) == LISTING_KEYS


def test_returns_a_subset_of_the_dataset():
    # Sanity: results are real listings drawn from the dataset, never invented.
    all_ids = {r["id"] for r in load_listings()}
    results = search_listings("vintage")
    assert {r["id"] for r in results}.issubset(all_ids)
