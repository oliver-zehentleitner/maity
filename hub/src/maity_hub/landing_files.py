"""The files of the landing page's progressive enhancement (docs/api.md §16.7).

`/assets/landing/landing.css`, `landing.js` and the self-hosted fonts under `fonts/` belong to
the hub's code, the same for every instance, and are never read from the database. They live in
this package (`landing_assets/`), so a hub answers them whether or not it has a dashboard
directory. The page names each with `?v=<digest>` of the file; a request that carries the
digest it should is answered `immutable`, any other is answered the current file with
`no-cache`, so a stale link repairs itself. The stylesheet holds `{font:<file>}` where a font
is named; they are replaced by the font's own versioned URL, so the fonts are cached for good as
well. The two pictures of the design and the logo are inline SVG in the page (`svg`).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

from maity_hub.errors import not_found

HERE = Path(__file__).with_name("landing_assets")  # the pictures, inline in the page
ROOT = HERE  # the files served; a test points it elsewhere
PREFIX = "/assets/landing/"
KINDS = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
}
FONT = re.compile(r"\{font:([a-z0-9-]+\.woff2)\}")
IMMUTABLE = "public, max-age=31536000, immutable"

router = APIRouter()


@dataclass(frozen=True)
class Asset:
    name: str
    kind: str
    body: bytes
    digest: str


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()[:16]


@cache
def _assets() -> dict[str, Asset]:
    """Every file the hub serves under `/assets/landing/`, by name: the stylesheet with its
    fonts' versioned URLs filled in, the script when it exists, the fonts and their licences."""
    found: dict[str, Asset] = {}

    def add(name: str, body: bytes) -> None:
        found[name] = Asset(name, KINDS[Path(name).suffix], body, _digest(body))

    fonts = ROOT / "fonts"
    if fonts.is_dir():
        for path in sorted(fonts.iterdir()):
            if path.suffix in (".woff2", ".txt"):
                add(f"fonts/{path.name}", path.read_bytes())
    agents = ROOT / "agents"
    if agents.is_dir():
        for path in sorted(agents.glob("*.svg")):
            add(f"agents/{path.name}", path.read_bytes())
        if (agents / "NOTICE").is_file():
            found["agents/NOTICE"] = Asset(
                "agents/NOTICE",
                KINDS[".txt"],
                (agents / "NOTICE").read_bytes(),
                _digest((agents / "NOTICE").read_bytes()),
            )
    script = ROOT / "landing.js"
    if script.is_file():
        add("landing.js", script.read_bytes())
    sheet = ROOT / "landing.css"
    if sheet.is_file():

        def font_url(found_font: re.Match[str]) -> str:
            name = f"fonts/{found_font.group(1)}"
            asset = found.get(name)
            return f"fonts/{found_font.group(1)}" + (f"?v={asset.digest}" if asset else "")

        add("landing.css", FONT.sub(font_url, sheet.read_text(encoding="utf-8")).encode())
    return found


def reset() -> None:
    """Forget what was read (a test changes the files)."""
    _assets.cache_clear()
    svg.cache_clear()


def url(name: str) -> str | None:
    """The versioned address of one file, or None when the hub has none of that name."""
    asset = _assets().get(name)
    return f"{PREFIX}{name}?v={asset.digest}" if asset else None


@cache
def svg(name: str) -> str:
    """One of the design's pictures, inline in the page."""
    return (HERE / name).read_text(encoding="utf-8").strip()


@router.api_route(PREFIX + "{name:path}", methods=["GET", "HEAD"], include_in_schema=False)
def serve(name: str, request: Request) -> Response:
    asset = _assets().get(name)
    if asset is None:
        raise not_found()
    current = request.query_params.get("v") == asset.digest
    etag = f'"{asset.digest}"'
    headers = {
        "Cache-Control": IMMUTABLE if current else "no-cache",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    # A revalidation of a file that has not changed costs no body (a stale link's `no-cache`).
    sent = {
        tag.strip().removeprefix("W/")
        for tag in request.headers.get("if-none-match", "").split(",")
    }
    if etag in sent or "*" in sent:
        return Response(status_code=304, headers=headers)
    return Response(asset.body, media_type=asset.kind, headers=headers)
