"""Styling for the Gradio operator dashboard."""

from __future__ import annotations

from enum import Enum


class Color(Enum):
    """Log line colours, keyed by span type."""

    RED = "#dd0000"
    GREEN = "#00dd00"
    YELLOW = "#dddd00"
    BLUE = "#0000ee"
    MAGENTA = "#aa00dd"
    CYAN = "#00dddd"
    WHITE = "#87CEEB"


#: Span type -> colour. Reading a panel then tells you what kind of work is
#: happening without reading the words: green is tool calls, yellow is the model
#: thinking, red is money moving.
LOG_COLORS = {
    "trace": Color.WHITE,
    "agent": Color.CYAN,
    "function": Color.GREEN,
    "generation": Color.YELLOW,
    "response": Color.MAGENTA,
    "account": Color.RED,
}

CSS = """
.positive-pnl { color: green !important; font-weight: bold; }
.negative-pnl { color: red !important; font-weight: bold; }
.dataframe-fix-small .table-wrap { min-height: 150px; max-height: 150px; }
.dataframe-fix .table-wrap { min-height: 200px; max-height: 200px; }
footer { display: none !important; }
"""

#: Force dark mode: this dashboard is meant to be left up on a second screen.
JS = """
function refresh() {
    const url = new URL(window.location);
    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.href = url.href;
    }
}
"""
