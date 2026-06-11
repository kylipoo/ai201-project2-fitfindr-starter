# Presence of this file at the project root puts the root on pytest's import
# path, so tests can `import tools` / `import agent` regardless of where pytest
# is launched from. Run the suite with `pytest`, not `python tests/<file>.py`.
#
# NOTE: everything runnable lives under `if __name__ == "__main__"` at the
# bottom, so it only fires when you run `python conftest.py` directly — NEVER
# when pytest imports this file. That keeps the live Groq call (Step 2) out of
# every test run.

from tools import search_listings, suggest_outfit
from utils.data_loader import load_listings, get_example_wardrobe, get_empty_wardrobe


def _ids(results):
    return [r["id"] for r in results]


def test_filters_by_max_price_inclusive(description, size, max_price):
    results = search_listings(description, size=size, max_price=max_price)
    print('The top result:', results if results else 'No results found')


def demo_search_then_outfit():
    """Walk the search -> suggest_outfit workflow with real data and a live LLM call."""
    # Step 1 — Search. size="L" is where the graphic / band tees live; with this
    # query that returns exactly 3 matches, sorted best-first.
    query, size, max_price = "vintage graphic tee", "L", 30.0
    print(f'Step 1 — Search: search_listings("{query}", size="{size}", max_price={max_price})')

    results = search_listings(query, size=size, max_price=max_price)
    print(f"  {len(results)} matches, best first:")
    for r in results:
        print(f"    - {r['title']} (${r['price']:.0f}, {r['platform']}, {r['condition']})")

    if not results:
        print("  No results — the workflow would stop here and set session['error'].")
        return

    # FitFindr always selects the top-ranked result (search returns them sorted).
    top = results[0]
    print(f"\n  FitFindr picks the top result: {top['title']} "
          f"(${top['price']:.0f}, {top['platform']}, {top['condition']})")

    # Step 2 — Suggest an outfit from that item + the user's wardrobe (live LLM).
    print(f"\nStep 2 — Suggest outfit: suggest_outfit(new_item=<{top['title']}>, wardrobe=<example>)")
    outfit = suggest_outfit(top, get_example_wardrobe())
    print(f"  (example wardrobe) {outfit}")

    # Empty wardrobe -> suggest_outfit gives general styling advice instead.
    empty_wardrobe_rec = suggest_outfit(top, get_empty_wardrobe())
    print(f"\n  (empty wardrobe)   {empty_wardrobe_rec}")


if __name__ == "__main__":
    demo_search_then_outfit()
