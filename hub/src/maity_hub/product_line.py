"""The product line (docs/api.md §16.13): one small line about Maity at the end of every page
of the platform's own interface, on the hub's own pages as on the dashboard's, always shown.

    [Maity icon] Maity 2026 · Found a bug? ·
    Made with ♥ by Oliver Zehentleitner on [GitHub icon] & [Maity icon]

The hub's pages load no file and many allow no style (`default-src 'self'`, the link pages'
`default-src 'none'`), so the icons are inline SVG with presentation attributes only and the
line needs no stylesheet: `<small>` keeps it small. A page whose policy allows a stylesheet
centres and mutes the line and switches the Maity mark's fill under a dark theme with
`STYLE`; every other page shows the light mark in either theme.
"""

from __future__ import annotations

import re
from html import escape

from maity_hub import catalog, clock

ISSUES = "https://github.com/oliver-zehentleitner/maity/issues"
GITHUB = "https://github.com/oliver-zehentleitner"
PROFILE = "https://maity.team/oliver-zehentleitner"
NAME = "Oliver Zehentleitner"
# The sentence's placeholders, each exactly once; a translation with one missing, one twice
# or another one is not used, the English sentence stands instead (§16.13, "Words").
PLACES = ("heart", "name", "github", "maity")
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# brand/maity-mark-small.svg without its role, label and <title>: decorative, or inside a
# link that has its name.
_MAITY_MARK = (
    '<svg viewBox="0 0 64 64" width="14" height="14" aria-hidden="true" focusable="false">'
    '<rect class="product-mark-t" x="24" y="2" width="16" height="16" rx="3" fill="#1a66d9"/>'
    + "".join(
        f'<circle class="product-mark-seat" cx="{x}" cy="{y}" r="8" fill="#1d2125"/>'
        for x, y in ((50, 22), (50, 44), (32, 54), (14, 44), (14, 22))
    )
    + "</svg>"
)
# GitHub's mark (Octicons, MIT), the path the dashboard draws for a GitHub repository.
_GITHUB_MARK = (
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">'
    '<path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17'
    ".55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15"
    "-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78"
    "-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64"
    "-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51"
    ".56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0"
    ' .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>'
)

# For a page whose policy allows its own stylesheet: the line centred and muted, as the
# dashboard draws it (§16.13, "How it looks"), and the dark mark's colours
# (brand/maity-mark-small-dark.svg) over the presentation attributes.
STYLE = (
    ".product-line{text-align:center;color:var(--muted,inherit);margin:1.5rem 0;padding:0 1rem}"
    ".product-line p{margin:0}.product-line a{color:inherit}"
    ".product-line svg{vertical-align:-2px}"
    "@media (prefers-color-scheme: dark){.product-mark-t{fill:#4c8dff}"
    ".product-mark-seat{fill:#e6e9ec}}"
)


def _link(href: str, inner: str, label: str | None = None) -> str:
    named = f' aria-label="{escape(label)}"' if label else ""
    return f'<a href="{href}" target="_blank" rel="noopener noreferrer"{named}>{inner}</a>'


def well_formed(text: str) -> bool:
    """Whether a sentence names each of the four placeholders exactly once and no other."""
    found = _PLACEHOLDER.findall(text)
    return len(found) == len(PLACES) and all(found.count(p) == 1 for p in PLACES)


def _sentence(language: str) -> str:
    """The credit in `language`: its text escaped, only the four placeholders become the
    fixed elements, never markup from the catalogue."""
    own = catalog.section("product", language)["made_by"]
    text = own if well_formed(own) else catalog.section("product", "en")["made_by"]
    love = catalog.section("product", language)["love"]
    elements = {
        "heart": f'<span role="img" aria-label="{escape(love)}">♥</span>',
        "name": escape(NAME),
        "github": _link(GITHUB, _GITHUB_MARK, "GitHub"),
        "maity": _link(PROFILE, _MAITY_MARK, "Maity"),
    }
    out, last = [], 0
    for found in _PLACEHOLDER.finditer(text):
        out.append(escape(text[last : found.start()]))
        out.append(elements[found[1]])
        last = found.end()
    out.append(escape(text[last:]))
    return "".join(out)


def html(language: str) -> str:
    """The line as a `<footer>`, in the language of the page it ends; the year from the hub's
    clock, in UTC, when the page is rendered."""
    bug = catalog.section("product", language)["bug"]
    parts = (
        f"{_MAITY_MARK} Maity {clock.now().year}",
        _link(ISSUES, escape(bug)),
        _sentence(language),
    )
    return f'<footer class="product-line"><p><small>{" · ".join(parts)}</small></p></footer>'
