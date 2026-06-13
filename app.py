"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:     The text the user typed into the search box.
        wardrobe_choice: Either "Example wardrobe" or "Empty wardrobe (new user)".

    Returns:
        A tuple of three strings:
            (listing_text, outfit_suggestion, fit_card)
        Each string maps to one of the three output panels in the UI.

    Guards against an empty query and returns early with a prompt message. Selects
    the wardrobe based on wardrobe_choice, then calls run_agent(). On error, returns
    the error message in the first panel with empty strings for the other two. Otherwise
    formats the selected item (including its match_quality) into listing_text and
    returns all three panels.
    """
    # 1. Guard against an empty query — don't run the agent on nothing.
    if not user_query or not user_query.strip():
        return "Type what you're looking for to get started.", "", ""

    # 2. Pick the wardrobe based on the radio selection.
    if wardrobe_choice.startswith("Empty"):
        wardrobe = get_empty_wardrobe()
    else:
        wardrobe = get_example_wardrobe()

    # 3. Run the planning loop.
    session = run_agent(user_query, wardrobe)

    # 4. On early-exit error, show it in the first panel only.
    if session["error"]:
        return session["error"], "", ""

    # 5. Otherwise format the listing and return all three panels.
    listing_text = _format_listing(
        session["selected_item"], session.get("match_quality", "exact")
    )
    return listing_text, session["outfit_suggestion"], session["fit_card"]


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


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["Example wardrobe", "Empty wardrobe (new user)"],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
