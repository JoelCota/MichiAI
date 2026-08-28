"""Opening things in the default browser."""

from __future__ import annotations

import urllib.parse
import webbrowser

from .registry import tool


@tool(
    group="web",
    description="Open a URL in the default browser.",
    parameters={"url": {"type": "string", "description": "The address to open."}},
    required=["url"],
)
def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opening {url}."


@tool(
    group="web",
    description=(
        "Run a web search in the browser. Use this when the user wants to SEE results. "
        "For questions you can answer yourself, just answer."
    ),
    parameters={
        "query": {"type": "string", "description": "What to search for."},
        "engine": {
            "type": "string",
            "enum": ["google", "duckduckgo", "youtube"],
            "description": "Which site to search. Defaults to google.",
        },
    },
    required=["query"],
)
def web_search(query: str, engine: str = "google") -> str:
    templates = {
        "google": "https://www.google.com/search?q=",
        "duckduckgo": "https://duckduckgo.com/?q=",
        "youtube": "https://www.youtube.com/results?search_query=",
    }
    base = templates.get(engine.lower(), templates["google"])
    webbrowser.open(base + urllib.parse.quote_plus(query))
    return f"Searching for {query}."
