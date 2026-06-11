"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


def _tokenize(text: str) -> set[str]:
    """Lowercase a string and split it into a set of alphanumeric word tokens."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


# ── Groq client ───────────────────────────────────────────────────────────────

# Default Groq model; override with GROQ_MODEL in .env if desired.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(messages: list[dict], temperature: float = 0.7) -> str:
    """Send a chat completion to Groq and return the assistant's text.

    This is the single network boundary for the LLM-backed tools; keeping it
    isolated lets the tools be unit-tested by stubbing this function out.
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return (response.choices[0].message.content or "").strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    query_tokens = _tokenize(description)
    size_query = _tokenize(size) if size else set()

    scored: list[tuple[int, dict]] = []
    for item in load_listings():
        # Filter: price ceiling (inclusive).
        if max_price is not None and item["price"] > max_price:
            continue

        # Filter: size, matched token-wise so "m" matches "S/M" but not "XL".
        if size_query and not size_query.issubset(_tokenize(item["size"])):
            continue

        # Score: keyword overlap across title, description, and style tags.
        searchable = _tokenize(
            f"{item['title']} {item['description']} {' '.join(item['style_tags'])}"
        )
        score = len(query_tokens & searchable)
        if score == 0:
            continue

        scored.append((score, item))

    # Sort by score, highest first. Python's stable sort keeps dataset order
    # for ties, so results are deterministic.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    messages = _build_outfit_messages(new_item, wardrobe)
    suggestion = _chat(messages, temperature=0.7).strip()
    if not suggestion:
        # The LLM should always answer, but never hand back an empty string.
        return (
            "Style it with simple, complementary basics in neutral tones and "
            "let the piece be the focus."
        )
    return suggestion


_OUTFIT_SYSTEM = (
    "You are FitFindr, a thrift-savvy personal stylist. Suggest 1-2 complete, "
    "wearable outfits. Be concrete and concise (a few sentences), warm and "
    "encouraging rather than salesy."
)


def _describe_item(new_item: dict) -> str:
    """Render a listing dict into a one-line description for the prompt."""
    title = new_item.get("title", "the item")
    details = []
    if new_item.get("category"):
        details.append(new_item["category"])
    if new_item.get("colors"):
        details.append(", ".join(new_item["colors"]))
    if new_item.get("style_tags"):
        details.append(", ".join(new_item["style_tags"]))
    return f"{title} ({'; '.join(details)})" if details else title


def _format_wardrobe(wardrobe: dict) -> str:
    """Render the user's wardrobe items into a bulleted list for the prompt."""
    lines = []
    for item in wardrobe.get("items") or []:
        line = item.get("name", "unnamed item")
        if item.get("colors"):
            line += f" ({', '.join(item['colors'])})"
        if item.get("notes"):
            line += f" — {item['notes']}"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _build_outfit_messages(new_item: dict, wardrobe: dict) -> list[dict]:
    """Build the chat messages for suggest_outfit, branching on wardrobe state."""
    item_desc = _describe_item(new_item)

    if wardrobe.get("items"):
        user = (
            f"The user is considering this secondhand item:\n{item_desc}\n\n"
            f"Here is what they already own (their wardrobe):\n"
            f"{_format_wardrobe(wardrobe)}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with specific "
            "pieces from their wardrobe. Name the wardrobe pieces you use."
        )
    else:
        user = (
            f"The user is considering this secondhand item:\n{item_desc}\n\n"
            "They have not entered a wardrobe yet, so give general styling "
            "advice: what kinds of pieces (types, colors, vibes) pair well with "
            "it and what overall look it suits. Do not invent specific items "
            "they own."
        )

    return [
        {"role": "system", "content": _OUTFIT_SYSTEM},
        {"role": "user", "content": user},
    ]


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    if not outfit or not outfit.strip():
        # Safety net: no styling content to build a caption from.
        return "Can't create a fit card without an outfit suggestion to work from."

    messages = _build_fit_card_messages(outfit, new_item)
    # Higher temperature than the other tools so captions vary across runs.
    caption = _chat(messages, temperature=1.0).strip()
    if not caption:
        title = new_item.get("title", "this piece")
        return f"Thrifted {title} and styled it up — a total score. ✨"
    return caption


_FIT_CARD_SYSTEM = (
    "You are FitFindr. Write a short, casual social-media caption for a "
    "secondhand fashion find — like a real OOTD post, not a product "
    "description. Sound authentic and a little excited, never salesy."
)


def _build_fit_card_messages(outfit: str, new_item: dict) -> list[dict]:
    """Build the chat messages for create_fit_card from the item and outfit."""
    name = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "")
    price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "a great price"

    user = (
        "Write a caption for this thrifted find.\n"
        f"Item: {name}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n\n"
        f"Styling: {outfit}\n\n"
        "Write 2-4 sentences. Work in the item name, price, and platform "
        "naturally — once each. Capture the outfit's vibe in specific terms. "
        "Keep it casual and authentic, like something a real person would post."
    )

    return [
        {"role": "system", "content": _FIT_CARD_SYSTEM},
        {"role": "user", "content": user},
    ]


# ── Query parsing (planning loop Step 2) ──────────────────────────────────────

_PARSE_SYSTEM = (
    "You parse a thrift-shopping query into JSON. Extract ONLY the item the "
    "user wants to BUY:\n"
    '- description: the item they are searching for (e.g. "vintage graphic tee")\n'
    "- size: the size they state, else null\n"
    "- max_price: a number if they give a price ceiling, else null\n"
    "Ignore anything they say they already OWN or WEAR. "
    'Return JSON only, no prose: {"description": ..., "size": ..., "max_price": ...}'
)


def _extract_json(text: str) -> str:
    """Pull the first {...} block out of an LLM response (tolerates fences/prose)."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def _coerce_float(value) -> float | None:
    """Best-effort convert a value to float, or None if it can't be."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_query(query: str) -> dict:
    """Extract {description, size, max_price} from a natural-language query.

    Uses the LLM at temperature 0 for a deterministic extraction. Always returns
    a dict with all three keys; on any failure it falls back to using the whole
    query as the description so the planning loop can still run a search.
    """
    messages = [
        {"role": "system", "content": _PARSE_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        raw = _chat(messages, temperature=0)
        data = json.loads(_extract_json(raw))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
    except Exception:
        return {"description": query, "size": None, "max_price": None}

    size = data.get("size")
    return {
        "description": data.get("description") or query,
        "size": str(size) if size is not None else None,
        "max_price": _coerce_float(data.get("max_price")),
    }
