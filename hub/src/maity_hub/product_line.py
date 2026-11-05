"""The product line (docs/api.md §16.13): one small line about Maity at the end of every page
of the platform's own interface, on the hub's own pages as on the dashboard's, always shown.

    [Maity icon] Maity 2026 · Found a bug? · Found a vulnerability? ·
    Made with ♥ by Oliver Zehentleitner on [GitHub icon] & [Maity icon]

The hub's pages load no file, so the icons are inline SVG with presentation attributes only.
The line's look is one fixed block, `STYLE`: centred and muted. A page whose policy allows
inline style (the registration page) puts it into its own stylesheet, with `DARK` for its
dark theme. The pages whose policy is the hub's `default-src 'self'` (the join page and the
`503` maintenance page; the mail link pages stand in the frame instead) put `HEAD` into their
`<head>` and answer with `HEADERS`: that policy allows exactly this block by its hash, never
`'unsafe-inline'`, and those pages have no dark theme, so the mark keeps its light fill.
"""

from __future__ import annotations

import base64
import hashlib
import re
from html import escape

from maity_hub import catalog, clock

ISSUES = "https://github.com/oliver-zehentleitner/maity/issues"
# Where a vulnerability is reported privately, never as a public issue.
SECURITY = "https://github.com/oliver-zehentleitner/maity/blob/main/SECURITY.md"
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

# The line centred and muted, as the dashboard draws it (§16.13, "How it looks"). A page
# without a `--muted` of its own gets the dashboard's light muted colour.
STYLE = (
    ".product-line{text-align:center;color:var(--muted,#5f6b76);margin:1.5rem 0;padding:0 1rem;"
    "border:0}.product-line p{margin:0}.product-line a{color:inherit;margin:0}"
    ".product-line svg{vertical-align:-2px}"
)
# A page with a dark theme: the dark mark's colours (brand/maity-mark-small-dark.svg) over
# the presentation attributes.
DARK = (
    "@media (prefers-color-scheme: dark){.product-mark-t{fill:#4c8dff}"
    ".product-mark-seat{fill:#e6e9ec}}"
)
# For a page whose policy allows no inline style: the block, and the policy that allows
# this block and no other (CSP 3, a hash source over the element's exact text). A change to
# `STYLE` changes the hash with it; tests/test_product_line.py checks they agree.
HEAD = f"<style>{STYLE}</style>"
STYLE_HASH = "sha256-" + base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
CSP = f"default-src 'self'; style-src '{STYLE_HASH}'"
# The token, where one is in the path, goes on in no `Referer` (§1.1, §16.13).
HEADERS = {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer"}


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


def html(language: str, section: str | None = None) -> str:
    """The line as a `<footer>`, in the language of the page it ends; the year from the hub's
    clock, in UTC, when the page is rendered. `section` names the page's own words: where
    the language has none for it yet, the page is English and so is its line."""
    if section is not None and not catalog.speaks(section, language):
        language = "en"
    words = catalog.section("product", language)
    parts = (
        f"{_MAITY_MARK} Maity {clock.now().year}",
        _link(ISSUES, escape(words["bug"])),
        _link(SECURITY, escape(words["security"])),
        _sentence(language),
    )
    # The separators are drawn, not read, as on the dashboard.
    dot = '<span aria-hidden="true"> · </span>'
    return f'<footer class="product-line"><p><small>{dot.join(parts)}</small></p></footer>'
