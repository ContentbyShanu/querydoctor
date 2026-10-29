"""Web dashboard assets.

The browser entry document is generated here so the repository contains only Python,
JavaScript and CSS. The interface itself is rendered by ``static/app.js``.
"""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"

_SHELL = (
    "<!doctype html>"
    '<html lang="en">'
    "<head>"
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="color-scheme" content="dark">'
    "<title>QueryDoctor</title>"
    '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">'
    '<link rel="stylesheet" href="/static/styles.css">'
    "</head>"
    '<body><div id="app" aria-live="polite"></div>'
    "<noscript>QueryDoctor needs JavaScript to render its dashboard.</noscript>"
    '<script type="module" src="/static/app.js"></script>'
    "</body></html>"
)


def render_shell() -> str:
    """Return the minimal document that boots the dashboard."""
    return _SHELL
