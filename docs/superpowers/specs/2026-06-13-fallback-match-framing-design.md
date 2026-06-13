# FitFindr — Honest framing for non-exact matches

**Date:** 2026-06-13
**Status:** Approved, ready for implementation plan

## Problem

`search_listings()` keeps any listing whose keyword-overlap score is above zero,
so a weak match can win and be presented as if it were exactly what the user
asked for.

Observed case: query "90s track jacket, size M, under $30" returned the
**90s Silk Slip Dress** as the "Top listing found". The real
**90s Track Jacket** exists but is $45, so the "under $30" filter removed it;
with no outerwear left under $30, the slip dress won on the shared "90s" token.
The UI then styled it and wrote a fit card as if it were a track jacket — which
reads like hallucination rather than a best-effort substitute.

## Goal

When the top result is not genuinely the kind of item the user asked for, say
so plainly in the listing panel ("Couldn't find an exact match for that — here's
the closest I found:") instead of presenting it as an exact hit. Stay quiet when
the match is genuine, or when we have no basis to judge.

## Approach: category matching

The mock dataset has a `category` field on every listing, with exactly five
values: `tops, bottoms, outerwear, shoes, accessories`. We infer the expected
category from the query and compare it to the top result's category. A mismatch
means the result is a fallback.

Chosen over alternatives (keyword-coverage ratio, head-noun match, LLM-judge,
embeddings, weighted scoring, universal soft framing) because it reuses
structured data already in the dataset, adds no new network call (the category
is extracted inside the existing parse step), and is fully deterministic and
testable offline.

Known limitation: the dataset lumps dresses into `bottoms`, and category
inference is only as good as the five-way bucket. Queries the LLM can't map to a
category (e.g. pure color/size queries) yield `None` and are treated as exact —
we deliberately do not cry wolf when we can't judge.

## Components (one change per layer)

### 1. `parse_query()` in `tools.py` — extract `category`
- Extend the existing single LLM call (temperature 0) to also return a
  `category` field, constrained to the five valid values or `null` when unclear.
- Normalize: lowercase the value; if it is not one of the five valid categories,
  coerce to `None`.
- The existing garbage/fallback path returns `category: None` alongside the other
  defaults. The returned dict gains one key (`"category"`); no existing key
  changes.

### 2. `run_agent()` in `agent.py` — compute match quality
- Add `"match_quality": "exact"` to `_new_session()` as the default.
- After selecting the top result, set `session["match_quality"]`:
  - parsed `category` is `None` → `"exact"` (no basis to doubt)
  - parsed `category` == `selected_item["category"]` → `"exact"`
  - otherwise → `"fallback"`
- The no-results early-exit path is unaffected (it returns before this step and
  surfaces `session["error"]`).

### 3. `app.py` — render the caveat
- In `_format_listing` (driven by `handle_query`), when
  `match_quality == "fallback"`, prepend a caveat line before the normal
  title/price/size block:
  > Couldn't find an exact match for that — here's the closest I found:
- Presentation stays in the app layer; the agent only returns the flag.

## Data flow

```
query → parse_query() → {description, size, max_price, category}
      → search_listings(description, size, max_price) → ranked listings
      → selected_item = listings[0]
      → match_quality = compare(parsed.category, selected_item.category)
      → suggest_outfit / create_fit_card  (unchanged)
app.py: if match_quality == "fallback", prepend caveat to listing panel
```

## Out of scope (YAGNI)

- The fallback item is still styled and still gets a fit card — only the
  listing-panel framing changes, not the downstream flow.
- No tiered "partial match" labels.
- No re-ranking or changes to `search_listings()` scoring.

## Testing (all offline, via existing stub seams)

- `test_parse_query.py`: stub `_chat` to return a `category`; assert it is parsed
  and normalized. Assert an invalid/missing category becomes `None`.
- `test_run_agent.py`: stub parsed + results so categories mismatch → assert
  `match_quality == "fallback"`; matching categories → `"exact"`; parsed
  `category None` → `"exact"`.
- `test_handle_query.py`: assert the caveat text appears on a fallback and is
  absent on an exact match.
