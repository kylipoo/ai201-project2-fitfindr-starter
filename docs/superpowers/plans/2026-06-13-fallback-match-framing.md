# Fallback Match Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the top search result is not the kind of clothing the user asked for, label it as a best-effort fallback in the listing panel instead of presenting it as an exact hit.

**Architecture:** Three isolated changes, one per layer. `parse_query()` extracts an expected `category` (constrained to the dataset's five values). `run_agent()` compares that category to the top result's category and records `session["match_quality"]` as `"exact"` or `"fallback"`. `app.py` prepends a caveat line to the listing panel when the match is a fallback. The agent owns the decision; the app owns the wording.

**Tech Stack:** Python, Groq LLM (already wired via `tools._chat`), pytest with `monkeypatch` stubbing of the LLM/tool seams (all tests run offline).

**Spec:** `docs/superpowers/specs/2026-06-13-fallback-match-framing-design.md`

---

## File Structure

- `tools.py` — `parse_query()` and its prompt/normalizers. Gains `category` extraction.
- `agent.py` — `run_agent()` planning loop and `_new_session()`. Gains a match-quality step + helper.
- `app.py` — `handle_query()` / `_format_listing()`. Gains the caveat rendering.
- `tests/test_parse_query.py`, `tests/test_run_agent.py`, `tests/test_handle_query.py` — new + updated cases.

The five valid categories (from `data/listings.json`): `tops, bottoms, outerwear, shoes, accessories`.

---

## Task 1: Extract `category` in `parse_query()`

**Files:**
- Modify: `tools.py` (`_PARSE_SYSTEM` ~L300-308; `parse_query` ~L330-354; add constants/helper)
- Modify: `tests/test_parse_query.py`

- [ ] **Step 1: Update + add failing tests**

In `tests/test_parse_query.py`, **replace** `test_always_returns_the_three_keys` (it asserts the exact key set, which now includes `category`) and **add** four new cases:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_parse_query.py -v`
Expected: the new tests FAIL (`KeyError: 'category'` / key-set mismatch); pre-existing tests still PASS.

- [ ] **Step 3: Add the category prompt, constant, and normalizer in `tools.py`**

Replace `_PARSE_SYSTEM` (currently ~L300-308) with:

```python
_PARSE_SYSTEM = (
    "You parse a thrift-shopping query into JSON. Extract ONLY the item the "
    "user wants to BUY:\n"
    '- description: the item they are searching for (e.g. "vintage graphic tee")\n'
    "- size: the size they state, else null\n"
    "- max_price: a number if they give a price ceiling, else null\n"
    "- category: the clothing category, one of "
    '"tops", "bottoms", "outerwear", "shoes", "accessories", '
    "or null if it does not clearly fit one\n"
    "Ignore anything they say they already OWN or WEAR. "
    "Return JSON only, no prose: "
    '{"description": ..., "size": ..., "max_price": ..., "category": ...}'
)

# The categories present in data/listings.json. Anything else is treated as
# "unknown" so the match-quality check stays conservative.
_VALID_CATEGORIES = {"tops", "bottoms", "outerwear", "shoes", "accessories"}


def _coerce_category(value) -> str | None:
    """Normalize a category to one of the known values, or None."""
    if not isinstance(value, str):
        return None
    category = value.strip().lower()
    return category if category in _VALID_CATEGORIES else None
```

- [ ] **Step 4: Add `category` to both return paths of `parse_query()`**

In `parse_query()`, change the exception fallback `return` (~L347) to:

```python
    except Exception:
        return {"description": query, "size": None, "max_price": None, "category": None}
```

and the success `return` (~L350-354) to:

```python
    size = data.get("size")
    return {
        "description": data.get("description") or query,
        "size": str(size) if size is not None else None,
        "max_price": _coerce_float(data.get("max_price")),
        "category": _coerce_category(data.get("category")),
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_parse_query.py -v`
Expected: PASS (all cases, including the four new ones).

- [ ] **Step 6: Commit**

```bash
git add tools.py tests/test_parse_query.py
git commit -m "feat: extract expected category in parse_query"
```

---

## Task 2: Compute `match_quality` in `run_agent()`

**Files:**
- Modify: `agent.py` (`_new_session` L36-45; `run_agent` after L111; add `_match_quality` helper)
- Modify: `tests/test_run_agent.py`

- [ ] **Step 1: Add failing tests**

Add to `tests/test_run_agent.py` (the existing `_stub_tools` helper accepts `parsed=` and `results=`):

```python
def test_category_mismatch_flags_fallback(monkeypatch):
    _stub_tools(
        monkeypatch,
        parsed={"description": "track jacket", "size": None, "max_price": None, "category": "outerwear"},
        results=[{"id": "x", "title": "Slip Dress", "price": 30.0, "platform": "depop", "category": "bottoms"}],
    )
    session = run_agent("track jacket", {"items": []})
    assert session["match_quality"] == "fallback"


def test_category_match_is_exact(monkeypatch):
    _stub_tools(
        monkeypatch,
        parsed={"description": "track jacket", "size": None, "max_price": None, "category": "outerwear"},
        results=[{"id": "x", "title": "Track Jacket", "price": 28.0, "platform": "depop", "category": "outerwear"}],
    )
    session = run_agent("track jacket", {"items": []})
    assert session["match_quality"] == "exact"


def test_no_category_is_treated_as_exact(monkeypatch):
    _stub_tools(
        monkeypatch,
        parsed={"description": "something blue", "size": None, "max_price": None, "category": None},
        results=[{"id": "x", "title": "Blue Thing", "price": 10.0, "platform": "depop", "category": "tops"}],
    )
    session = run_agent("something blue", {"items": []})
    assert session["match_quality"] == "exact"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_run_agent.py -v`
Expected: the three new tests FAIL (`KeyError: 'match_quality'`); pre-existing tests still PASS (their stubbed `parsed` has no `category`, which the helper treats as `None`).

- [ ] **Step 3: Add the default field to `_new_session()`**

In `agent.py`, add this line to the dict returned by `_new_session()` (alongside the other fields, before `"error": None`):

```python
        "match_quality": "exact",    # "exact" or "fallback" (see _match_quality)
```

- [ ] **Step 4: Add the match-quality step and helper in `agent.py`**

In `run_agent()`, immediately after Step 4 (`session["selected_item"] = session["search_results"][0]`), insert:

```python
    # Step 4b — Judge whether the top result is the right kind of item, so the
    # UI can be honest when it had to fall back to a near-miss.
    session["match_quality"] = _match_quality(parsed, session["selected_item"])
```

Add this helper near `_no_results_message` (after the `run_agent` function):

```python
def _match_quality(parsed: dict, item: dict) -> str:
    """Return "exact" or "fallback" by comparing parsed category to the item.

    When the query has no clear category, we have no basis to doubt the top
    result, so we treat it as exact rather than crying wolf.
    """
    expected = parsed.get("category")
    if expected is None:
        return "exact"
    return "exact" if expected == item.get("category") else "fallback"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_run_agent.py -v`
Expected: PASS (all cases).

- [ ] **Step 6: Commit**

```bash
git add agent.py tests/test_run_agent.py
git commit -m "feat: record match_quality in run_agent"
```

---

## Task 3: Render the fallback caveat in `app.py`

**Files:**
- Modify: `app.py` (`handle_query` L64-65; `_format_listing` L68-80; add `_FALLBACK_NOTE`)
- Modify: `tests/test_handle_query.py`

- [ ] **Step 1: Add failing tests**

In `tests/test_handle_query.py`, add `"match_quality": "exact",` to the base dict inside the `_session()` helper (so it mirrors the real session shape), then add:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_handle_query.py -v`
Expected: `test_fallback_prepends_caveat_to_listing` FAILS (no caveat text yet); `test_exact_match_has_no_caveat` PASSES; pre-existing tests still PASS.

- [ ] **Step 3: Thread `match_quality` into `_format_listing` from `handle_query`**

In `app.py`, change the Step-5 formatting line (~L64) to:

```python
    # 5. Otherwise format the listing and return all three panels.
    listing_text = _format_listing(
        session["selected_item"], session.get("match_quality", "exact")
    )
```

(`.get(..., "exact")` keeps `handle_query` safe even if a session ever lacks the field.)

- [ ] **Step 4: Render the caveat in `_format_listing`**

Replace `_format_listing` (~L68-80) with:

```python
_FALLBACK_NOTE = "Couldn't find an exact match for that — here's the closest I found:"


def _format_listing(item: dict, match_quality: str = "exact") -> str:
    """Render the selected listing dict into readable text for the UI panel."""
    lines = []
    if match_quality == "fallback":
        lines.append(_FALLBACK_NOTE)
        lines.append("")
    lines += [
        item.get("title", "Untitled listing"),
        f"${item.get('price', 0):.2f} · {item.get('platform', '')}",
        f"Size {item.get('size', '?')} · {item.get('condition', '?')} condition",
    ]
    if item.get("brand"):
        lines.append(f"Brand: {item['brand']}")
    if item.get("description"):
        lines.append("")
        lines.append(item["description"])
    return "\n".join(lines)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_handle_query.py -v`
Expected: PASS (all cases).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_handle_query.py
git commit -m "feat: show fallback caveat in listing panel"
```

---

## Task 4: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the entire offline suite**

Run: `pytest -v`
Expected: PASS — all tests green. (Live tests are skipped unless `FITFINDR_LIVE_TESTS=1`.)

- [ ] **Step 2 (optional): End-to-end live check of the original bug**

Run: `FITFINDR_LIVE_TESTS=1 python -c "from agent import run_agent; from utils.data_loader import get_example_wardrobe; s = run_agent('90s track jacket, size M, under \$30', get_example_wardrobe()); print(s['match_quality'], '—', s['selected_item']['title'])"`
Expected: prints `fallback — 90s Silk Slip Dress — Floral, Midi Length` (the real jacket is $45, so the slip dress is correctly flagged as a fallback).

---

## Self-Review

- **Spec coverage:** parse_query category extraction → Task 1; run_agent match_quality decision (None/match/mismatch) → Task 2; app caveat rendering → Task 3; offline tests across all three layers → Tasks 1-3; full-suite + e2e → Task 4. No gaps.
- **Placeholders:** none — every code/test step shows complete content.
- **Type consistency:** `category` is `str | None` everywhere; `match_quality` is the string `"exact"`/`"fallback"` in `_new_session`, `_match_quality`, `handle_query`, and `_format_listing`. `_VALID_CATEGORIES`, `_coerce_category`, `_match_quality`, `_FALLBACK_NOTE` names are used consistently.
- **Breaking-change guards:** the existing `test_always_returns_the_three_keys` is replaced (Task 1 Step 1); `app.py` uses `.get("match_quality", "exact")` so any session without the field is safe.
