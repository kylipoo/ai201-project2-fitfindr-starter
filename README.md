# FitFindr 🛍️

FitFindr is a small agent that turns a natural-language thrift query
("90s track jacket in size M, under $30") into three things: a matching
secondhand listing, an outfit built around it using your wardrobe, and a
shareable OOTD-style "fit card" caption.

It is not a chatbot and not a single LLM call. It is a **planning loop** —
a fixed sequence of steps that calls three tools in order, threads state
between them through one session dict, and bails out early (with a helpful
message) the moment a step can't produce valid input for the next one.

```
"90s track jacket in size M, under $30"
        │
        ▼
  parse the query ──► search listings ──► suggest an outfit ──► write a fit card
        │                  │                                          │
        │             no match? stop here                            ▼
        ▼             with a helpful message            🛍️ listing  👗 outfit  ✨ fit card
   {description, size,                                  (the three UI panels)
    max_price, category}
```

The rest of this README explains **what decisions the agent makes** at each
step, not just which functions exist.

---

## Setup & running

```bash
pip install -r requirements.txt          # groq, python-dotenv, gradio, pytest
```

Set a free Groq API key in a `.env` file in the project root
(get one at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
# optional: GROQ_MODEL=llama-3.3-70b-versatile   (the default)
```

Run the app end-to-end:

```bash
python app.py
```

Then open the localhost URL printed in your terminal (usually
`http://localhost:7860` — check the terminal, the port can differ). Type a
query, pick a wardrobe, and the three output panels populate.

You can also run the loop headless (no UI) to see the happy path and the
no-results path:

```bash
python agent.py
```

Run the test suite (all offline — the LLM boundary is stubbed):

```bash
pytest
```

---

## Tool inventory

The three required tools live in [tools.py](tools.py). Each is a **standalone,
stateless function** — it takes explicit arguments, returns a value, and never
reads or writes the session. That's what lets them be unit-tested in isolation.
A fourth helper, `parse_query()`, runs as Step 2 of the loop and is documented
alongside them.

### 1. `search_listings` — the only non-LLM tool (deterministic lookup)

| | |
|---|---|
| **Purpose** | Search the 40-item mock dataset for listings matching the description, with optional size and price filters, ranked best-match-first. |
| **Inputs** | `description: str` — keywords the user is shopping for. <br> `size: str \| None` — size filter; `None` skips it. Matched token-wise so `"M"` matches `"S/M"` but not `"XL"`. <br> `max_price: float \| None` — inclusive price ceiling; `None` skips it. |
| **Output** | `list[dict]` — matching listing dicts sorted by keyword-overlap score, highest first. **Returns `[]` when nothing matches — never raises.** |

How it ranks: it scores each surviving listing by the number of shared word
tokens between the query and the listing's `title + description + style_tags`,
drops anything scoring 0, and sorts descending. Python's stable sort keeps
dataset order for ties, so results are deterministic.

### 2. `suggest_outfit` — generative (LLM)

| | |
|---|---|
| **Purpose** | Given a thrifted item and the user's wardrobe, ask the LLM for 1–2 complete, wearable outfits. |
| **Inputs** | `new_item: dict` — the listing the user is considering (usually the top search result). <br> `wardrobe: dict` — a dict with an `items` list of the user's pieces. **May be empty.** |
| **Output** | `str` — a non-empty outfit suggestion. **Never empty, never raises.** |

Branching decision: if `wardrobe["items"]` has pieces, the prompt asks for
outfits that name **specific owned pieces**. If it's empty, the prompt switches
to **general styling advice** (what kinds of pieces/colors/vibes pair well) and
is explicitly told not to invent items the user owns.

### 3. `create_fit_card` — generative (LLM, high temperature)

| | |
|---|---|
| **Purpose** | Turn the outfit suggestion into a short, casual OOTD-style caption for sharing. |
| **Inputs** | `outfit: str` — the suggestion string from `suggest_outfit`. <br> `new_item: dict` — the listing dict; supplies name, price, platform. |
| **Output** | `str` — a 2–4 sentence caption that works in the name, price, and platform once each. Runs at `temperature=1.0` so different inputs read differently. |

### Loop helper: `parse_query` — natural-language → structured params (LLM)

| | |
|---|---|
| **Purpose** | Step 2 of the loop: extract structured search params from messy phrasing like "under 30 bucks" or "size medium-ish". |
| **Inputs** | `query: str` — the raw user query. |
| **Output** | `dict` with four keys, always present: `description: str`, `size: str \| None`, `max_price: float \| None`, `category: str \| None` (one of `tops/bottoms/outerwear/shoes/accessories`, or `None`). |

It calls the LLM at `temperature=0` for a deterministic extraction and is told
to ignore anything the user says they already *own*. On any parse failure it
falls back to using the whole query as the `description` so the search can still
run.

> **One network boundary.** All four LLM-backed functions call through a single
> private `_chat()` helper in [tools.py](tools.py#L48). Isolating the network
> call there is what makes the tools unit-testable offline — the tests stub
> `_chat` instead of hitting Groq.

---

## How the planning loop works

The loop lives in `run_agent()` in [agent.py](agent.py#L51). It is **linear with
early-exit guards**, not a free-form "let the model pick a tool" loop. The
sequence is fixed; what changes per run is *whether it completes or bails early*,
and *which prompt branch* the generative tools take.

**The decisions the agent makes, in order:**

1. **Initialize** — build a fresh session dict (the single source of truth for
   this run). All result fields start empty; `error` starts `None`.

2. **Parse the query** → `session["parsed"]`. Decide what the user is *buying*
   (description), and whether they constrained size, price, or an item category.
   Unstated constraints stay `None`.

3. **Search, then branch.** Call `search_listings`.
   - **Decision — any results?** If the list is **empty**, set
     `session["error"]` to a specific, actionable message and **return
     immediately**. The agent does *not* call `suggest_outfit` with no item —
     that's the key planning decision that keeps it from styling nothing.
   - If non-empty, continue.

4. **Select** the top-ranked result (`search_results[0]`) → `selected_item`.

5. **Judge match quality** (`exact` vs `fallback`). Compare the parsed
   `category` to the selected item's `category`:
   - parsed category is `None` → **`exact`** (no basis to doubt — don't cry wolf)
   - categories match → **`exact`**
   - categories differ → **`fallback`** (the search had to substitute a
     near-miss; the UI will say so honestly)

6. **Suggest an outfit** → `outfit_suggestion`. No branch needed in the loop:
   the tool always returns a non-empty string, so the loop can always proceed.

7. **Create the fit card** → `fit_card`, then **return** the session.

**How it knows it's done:** the loop terminates either at the Step 3 early
return (no results → `error` set, outputs stay `None`) or after Step 7 (success
→ `fit_card` populated, `error` is `None`). The caller checks `session["error"]`
first to tell the two apart — that's how [app.py](app.py#L56) decides whether to
show an error in the listing panel or render all three panels.

---

## State management

**All state for one interaction lives in a single `session` dict**, created by
`_new_session(query, wardrobe)` in [agent.py](agent.py#L26). There is no global
or cross-request state — one dict per `run_agent()` call.

The tools are stateless and never touch the session. **The planning loop is the
only thing that reads from and writes to it**: after each tool returns, the loop
stores the result in a session field, then reads the field it needs to build the
next tool's arguments. Every hand-off is explicit — nothing is passed implicitly.

| Field | Set by | Consumed by |
|---|---|---|
| `query` | Step 1 (caller) | Step 2 — parsing |
| `parsed` | Step 2 | Step 3 — `description`/`size`/`max_price`; Step 5 — `category` for match quality |
| `search_results` | Step 3 | Step 4 select + the empty-check that branches to error |
| `selected_item` | Step 4 (`search_results[0]`) | Step 5 + Step 7 (`new_item`) |
| `wardrobe` | Step 1 (caller) | Step 6 (`suggest_outfit`) |
| `match_quality` | Step 5 (`"exact"`/`"fallback"`) | the UI listing panel |
| `outfit_suggestion` | Step 6 | Step 7 (`create_fit_card`) |
| `fit_card` | Step 7 | final output to user |
| `error` | any step, on early exit | caller — checked first to distinguish success vs. failure |

Because every hand-off is a named field, the full state of any run can be
inspected by printing the session dict — which is exactly what the `__main__`
block in [agent.py](agent.py#L162) does for the happy and no-results paths.

---

## Error handling (per tool)

The agent distinguishes **expected, designed-for failures** (which it recovers
from gracefully) from **unexpected ones** (which surface as clear errors rather
than being silently swallowed).

| Tool | Failure mode | What the agent does |
|---|---|---|
| `search_listings` | No listing matches the query | Tool returns `[]` (never raises). The loop detects the empty list in Step 3, sets a **specific actionable** `error`, and returns **before** calling `suggest_outfit`. Outputs stay `None`. |
| `suggest_outfit` | Wardrobe is empty | **Not an error.** The tool branches its prompt to general styling advice and always returns a non-empty string, so the loop continues normally. |
| `create_fit_card` | `outfit` is empty/whitespace | Returns a **descriptive error string** instead of raising or calling the LLM — a safety net for a malformed upstream step (never fires in the happy path, since `suggest_outfit` is always non-empty). |
| any LLM tool | Missing key, network/rate-limit error | `_get_groq_client()` raises a descriptive `ValueError` when `GROQ_API_KEY` is unset; other Groq exceptions are allowed to surface rather than be hidden behind a fake result. |

**Concrete example — the no-results path.** Query:
`"designer ballgown size XXS under $5"`. Nothing in the dataset is a ballgown in
XXS under $5, so `search_listings` returns `[]`. The loop sets:

> *"No listings matched 'designer ballgown', size XXS, under $5. Try loosening
> the description, raising the price, or dropping the size filter."*

…and returns early. The UI shows that message in the listing panel and leaves
the outfit and fit-card panels empty — no hallucinated styling of an item that
doesn't exist.

**Concrete example — honest fallback framing.** Query:
`"90s track jacket in size M, under $30"`. The real 90s Track Jacket is $45, so
the `under $30` filter removes it; with no outerwear left, the **90s Silk Slip
Dress** wins on the shared "90s" token. Rather than present a dress as if it
were the requested jacket, Step 5 flags `match_quality = "fallback"` (parsed
category `outerwear` ≠ item category `bottoms`) and the listing panel prepends:

> *"Couldn't find an exact match for that — here's the closest I found:"*

The item is still styled and still gets a fit card; only the framing changes, so
the agent stays honest instead of reading like a hallucination.

---

## Spec reflection

Writing [planning.md](planning.md) before any code paid off most where the spec
was **a decision, not a description**. Two examples:

- **"Return `[]`, don't raise" was a spec decision that shaped the whole loop.**
  Because Tool 1's failure mode was pinned down up front, the planning loop's
  hardest design choice — *don't call `suggest_outfit` with no item* — fell out
  naturally as an early return. If I'd discovered the empty-results case while
  coding, I'd likely have bolted on a `try/except` somewhere downstream instead.

- **The spec under-specified parsing, and that gap showed up later.** The
  original planning.md tracked only three parsed fields
  (`description`, `size`, `max_price`) and left parsing as "regex *or* LLM." When
  I later hit the slip-dress-as-track-jacket problem, I had to extend the parse
  contract with a fourth field (`category`) to judge match quality. The lesson:
  the spec was right about the *happy path* but didn't anticipate **how the agent
  should behave when the best match is a bad match** — honesty about quality was
  a requirement I only articulated after seeing the failure.

What I'd change: the planning.md "A Complete Interaction" section imagined the
agent parsing free-form wardrobe text from the query ("I mostly wear baggy
jeans…"). The shipped design is simpler and cleaner — the wardrobe is a
structured input (example vs. empty), not something parsed out of the query —
and I'd write the spec that way from the start rather than describing a more
ambitious parse I didn't build.

---

## AI usage

I used **Claude (Claude Code)** as the implementation tool throughout, driving it
from the specs in planning.md rather than from vague prompts. Two specific
instances:

### Instance 1 — generating the tools and the planning loop from the spec

- **What I gave it:** the **Tool 1–3 sections** of planning.md (inputs, return
  shapes, and the exact failure modes — "returns `[]`, never raises"; "never
  empty, never raises"; the empty-outfit guard), the **Planning Loop / State
  Management / Error Handling** sections, the **Mermaid architecture diagram**,
  the `_new_session()` field list, and the `load_listings()` signature from
  [utils/data_loader.py](utils/data_loader.py).
- **What it produced:** `search_listings` (keyword-overlap scoring + size/price
  filters), the two LLM tools with their prompt-branching, and `run_agent()`
  implementing the 7-step sequence with the early return on empty results.
- **What I changed / overrode before trusting it:**
  - **Added a `_chat()` seam.** The generated tools called the Groq client
    inline. I refactored every LLM call through one private `_chat()` boundary so
    the tools are unit-testable offline — the tests stub `_chat`, not the
    network. This was my architectural call, not the model's.
  - **Verified against the failure paths, not just the happy path.** I ran the
    no-results query (`designer ballgown size XXS under $5`) and the empty-
    wardrobe case before trusting the loop, confirming the early return fired
    *before* `suggest_outfit` and that the outfit/fit-card fields stayed `None`.
  - **Tightened the prompts** so `suggest_outfit` names real owned pieces in the
    populated-wardrobe branch and is explicitly told *not* to invent items in the
    empty branch.

### Instance 2 — the honest-fallback feature (design spec → implementation)

- **What I gave it:** a written **design spec**
  ([docs/superpowers/specs/2026-06-13-fallback-match-framing-design.md](docs/superpowers/specs/2026-06-13-fallback-match-framing-design.md))
  describing the problem (a weak keyword match — the 90s slip dress — being
  presented as an exact hit for a track-jacket query), and the chosen approach
  (compare the query's inferred `category` to the result's `category`).
- **What it produced:** a three-layer implementation — extend `parse_query` to
  return a normalized `category`, compute `match_quality` in `run_agent`, and
  prepend a caveat line in `app.py`'s `_format_listing` — plus offline tests for
  each layer.
- **What I changed / overrode before trusting it:**
  - **Kept the scope to framing only.** I rejected re-ranking or tiered
    "partial match" labels (YAGNI) — the fallback item is still styled and still
    gets a fit card; *only the listing-panel wording changes*.
  - **Chose the conservative "don't cry wolf" rule.** When the query has no clear
    category (e.g. a pure color/size search), `category` is `None` and the agent
    treats the result as `exact` rather than flagging a fallback it can't justify.
    I picked category-matching over the LLM-judge and embedding alternatives the
    model offered because it reuses structured data already in the dataset, adds
    no new network call, and is fully deterministic and testable offline.

---

## Repository map

```
ai201-project2-fitfindr-starter/
├── app.py                 # Gradio UI + handle_query → maps session to 3 panels
├── agent.py               # run_agent(): the planning loop + session state
├── tools.py               # search_listings, suggest_outfit, create_fit_card, parse_query
├── planning.md            # the spec this implementation was built from
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # wardrobe format + example/empty wardrobes
├── utils/data_loader.py   # load_listings / get_example_wardrobe / get_empty_wardrobe
├── tests/                 # offline unit tests (LLM boundary stubbed via _chat)
└── docs/                  # design spec + implementation plan for the fallback feature
```
