"""tsk-d0ktrdakakhp: a public page stands on its own without JavaScript. A visitor without a
session gets a stored page inside the app shell (§16.11), whose header and footer used to be
drawn by `js/site-chrome.js` alone; the hub now serves them in the HTML (hub/context/
public-pages.md). Every family of public page is fetched here as a client that runs no script
reads it: the header's and the footer's links are in the bytes, in the visitor's language."""

from __future__ import annotations

import re
import shutil
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import public_pages
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import BASE, TASKS, World

REAL_SHELL = Path(__file__).resolve().parents[2] / "web" / "index.html"


@pytest.fixture(autouse=True)
def _real_shell(web_dir: Path) -> None:
    """The dashboard's own `index.html`, the document a visitor's browser gets."""
    shutil.copyfile(REAL_SHELL, web_dir / "index.html")


class Frame(HTMLParser):
    """What a client without script finds of the frame: each `<header class="site-header">` and
    `<footer class="site-footer">`, their links and the language they say; the app's own bar
    (`<header id="header">`), and whether it is hidden."""

    def __init__(self, html: str, served: bool = True) -> None:
        super().__init__()
        self.served = served
        self.header: list[tuple[str, str]] = []
        self.footer: list[tuple[str, str]] = []
        self.header_lang: str | None = None
        self.footer_lang: str | None = None
        self.bar_hidden: bool | None = None
        self.order: list[str] = []
        self.hrefs: list[str] = []
        self._in: str | None = None
        self._href: str | None = None
        self._text = ""
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "header" and a.get("id") == "header":
            self.bar_hidden = "hidden" in a
            self.order.append("bar")
        elif tag == "header" and "site-header" in classes:
            self._in, self.header_lang = "header", a.get("lang")
            assert not self.served or (a.get("id") == "site-header" and "data-served-frame" in a)
            self.order.append("header")
        elif tag == "footer" and "site-footer" in classes:
            self._in, self.footer_lang = "footer", a.get("lang")
            assert not self.served or (a.get("id") == "site-footer" and "data-served-frame" in a)
            self.order.append("footer")
        elif tag == "main":
            self.order.append("main")
        elif tag == "a" and self._in:
            self._href, self._text = a.get("href") or "", ""
            self.hrefs.append(self._href)

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            (self.header if self._in == "header" else self.footer).append(
                (self._text.strip(), self._href)
            )
            self._href = None
        elif tag in ("header", "footer") and self._in == tag:
            self._in = None


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    made = World(make_client, migrated)

    # A landing page as on production: the four header links, open-source and social columns,
    # legal pages and a language switch. The earlier screenshot's empty nav was only this
    # fixture having a hero and no `nav_label` sections, not the served frame leaving them out.
    def sections(works: str, teams: str, source: str, faq: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "hero",
                "enabled": True,
                "title": "Bring your agents.",
                "cta_primary": {"label": "Create your account", "href": "/register"},
            },
            {
                "type": "steps",
                "enabled": True,
                "title": works,
                "nav_label": works,
                "items": [{"title": "Join", "text": "Run it."}],
            },
            {
                "type": "scales",
                "enabled": True,
                "title": teams,
                "nav_label": teams,
                "items": [
                    {"tag": "You", "title": "You", "text": "One project.", "points": ["One"]}
                ],
            },
            {
                "type": "opensource",
                "enabled": True,
                "title": source,
                "nav_label": source,
                "tiles": [{"title": "MIT", "text": "Read it."}],
                "links": [
                    {"label": "GitHub", "href": "https://github.com/oliver-zehentleitner/maity"},
                    {"label": "Keep the Why", "href": "https://keepthewhy.com"},
                ],
            },
            {
                "type": "faq",
                "enabled": True,
                "title": faq,
                "nav_label": faq,
                "items": [{"q": "What is it?", "a": "A hub."}],
            },
        ]

    pages = {
        "en": {
            "title": "Maity",
            "description": "A hub",
            "sections": sections("How it works", "For you & teams", "Open Source", "FAQ"),
        },
        "de": {
            "title": "Maity",
            "description": "Ein Hub",
            "sections": sections("So funktioniert's", "Für dich & Teams", "Open Source", "FAQ"),
        },
    }
    saved = made.owner.patch(
        "/admin/settings/landing",
        {
            "enabled": True,
            "default_language": "en",
            "pages": pages,
            "footer": {
                "operator": "Oliver Zehentleitner",
                "social": [
                    {"label": "X", "href": "https://x.com/maityteam"},
                    {"label": "Mastodon", "href": "https://mastodon.social/@maityteam"},
                ],
            },
        },
    )
    assert saved.status_code == 200, saved.text
    # One legal page per call (`one_page_per_call`).
    for key, en, de in (
        ("imprint", "Imprint", "Impressum"),
        ("privacy", "Privacy", "Datenschutz"),
        ("terms", "Terms", "Nutzungsbedingungen"),
    ):
        done = made.owner.patch(
            "/admin/settings/legal",
            {
                key: {
                    "en": {"title": en, "markdown": "Maity."},
                    "de": {"title": de, "markdown": "Maity."},
                }
            },
        )
        assert done.status_code == 200, done.text
    return made


def unbased(links: list[tuple[str, str]], path: str) -> list[tuple[str, str]]:
    """Links as `/explore` writes them: the footer's languages there are a bare `?lang=`, which
    in the shell would lead into `/assets/` and so are this page's own path first."""
    return [
        (label, href.removeprefix(path) if href.startswith(f"{path}?") else href)
        for label, href in links
    ]


def families(world: World) -> dict[str, str]:
    """One address of every family of public page the hub stores, by the kind it is stored as."""
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    card = world.owner.post(TASKS, {"title": "Next up"}).json()["id"]
    assert (
        world.owner.post("/orgs", {"handle": "acme-inc", "display_name": "Acme"}).status_code == 201
    )
    assert world.owner.patch("/orgs/acme-inc", {"public_page": "on"}).status_code == 200
    world.touch()
    handle = world.bot.get("/me").json()["member"]["handle"]
    found = {
        "project": BASE,
        "project_views": f"{BASE}/board",
        "card": f"{BASE}/tasks/{card}",
        "person": "/maintainer",
        "agent": f"/maintainer/agents/{handle}",
        "organisation": "/acme-inc",
    }
    with world.migrated.connect() as conn:
        stored = dict(conn.execute(select(t.public_page.c.path, t.public_page.c.kind)).all())
    # Every address is a stored page, of the kind it stands for: none is the dashboard's shell.
    assert {stored.get(path) for path in found.values()} == set(found)
    assert [stored[path] for path in found.values()] == list(found)
    return found


def test_every_family_has_the_frames_links_in_its_html(world: World) -> None:
    """The card's check: the page's HTML as served, no script run, holds the header's links
    (the mark, the sections, Sign in, the call to action) and the footer's (the legal pages, the
    platform and open source columns), as the pages the hub frames itself (`/explore`)."""
    explore = Frame(world.anyone.get("/explore").text, served=False)
    # The same frame, left out the theme switch the landing's script adds: links and words.
    assert explore.header and explore.footer
    assert explore.header[0] == ("maity", "/")
    assert any(href.startswith("/login") for _, href in explore.header)
    for kind, path in families(world).items():
        got = world.anyone.get(path)
        assert got.status_code == 200, kind
        page = Frame(got.text)
        assert "js/app.js" in got.text, kind  # it is the shell, the dashboard takes over
        # Header: the same links as `/explore`'s; Sign in comes back to this very page.
        by_label = dict(page.header)
        assert [label for label, _ in page.header] == [label for label, _ in explore.header], kind
        sign_in = next(href for _, href in page.header if href.startswith("/login"))
        assert sign_in.endswith(f"next={path.replace('/', '%2F')}"), (kind, sign_in)
        assert by_label["maity"] == "/"
        for label, href in explore.header:
            if not href.startswith("/login"):
                assert (label, href) in page.header, (kind, label)
        # Footer: every link of `/explore`'s, none left to a script.
        assert unbased(page.footer, path) == explore.footer and len(page.footer) >= 3, kind
        # The frame stands where the dashboard draws it: the app's bar, hidden, then the
        # header, the page, the footer.
        assert page.order == ["bar", "header", "main", "footer"], kind
        assert page.bar_hidden is True, kind
        # A link of the frame never leads into `/assets/` under the shell's `<base>`.
        assert all(h.startswith(("/", "https://", "mailto:")) for h in page.hrefs), kind
        assert 'class="public-frame"' in got.text and "/assets/landing/landing.css" in got.text
        # The stored page stands as it was stored: nothing of the frame is in its row.
    with world.migrated.connect() as conn:
        assert "site-header" not in " ".join(conn.execute(select(t.public_page.c.body)).scalars())


def test_the_visitors_language_is_the_frames_without_script(world: World) -> None:
    """`?lang` and `Accept-Language` choose the frame's words as for any page in the frame."""
    path = families(world)["project"]
    english = Frame(world.anyone.get(path).text)
    german = Frame(world.anyone.get(path, params={"lang": "de"}).text)
    reader = Frame(world.anyone.get(path, headers={"Accept-Language": "de"}).text)
    assert german.header != english.header or german.footer != english.footer
    assert reader.header == german.header and reader.footer == german.footer
    # The page's own words are English: the frame says its own language where it differs.
    assert german.header_lang == "de" == german.footer_lang
    assert english.header_lang is None
    assert "Accept-Language" in world.anyone.get(path).headers["vary"]
    # The same words as `/explore` in that language.
    explore = Frame(world.anyone.get("/explore", params={"lang": "de"}).text, served=False)
    assert unbased(german.footer, path) == explore.footer


def test_the_languages_of_the_footer_stay_on_this_page(world: World, migrated: Engine) -> None:
    """A bare `?lang=` would lead into `/assets/` under the shell's `<base href="/assets/">`."""
    from maity_hub import landing

    with migrated.begin() as conn:
        setting = landing.stored(conn)
    assert setting["enabled"]
    path = families(world)["project"]
    page = Frame(world.anyone.get(path).text)
    langs = [h for _, h in page.footer if h.startswith(f"{path}?lang=")]
    assert langs and all(h.startswith(f"{path}?lang=") for h in langs)


def test_the_frame_is_part_of_the_pages_tag(world: World) -> None:
    """A change of the frame's words changes the bytes, so it changes the tag: a cache is never
    given a 304 for another language's page."""
    path = families(world)["project"]
    english = world.anyone.get(path)
    german = world.anyone.get(path, params={"lang": "de"})
    assert english.headers["etag"] != german.headers["etag"]
    assert (
        world.anyone.get(path, headers={"If-None-Match": english.headers["etag"]}).status_code
        == 304
    )


def test_the_crumb_of_a_project_page_links_the_owner_and_the_project(world: World) -> None:
    """tsk-d0ktrdakakhp: `owner / slug` above the title is two plain links in the stored HTML,
    the owner's public page and the project's own, on the Overview as on the other views and a
    card, so they work without script. The row's format is the one that has them."""
    found = families(world)
    for kind in ("project", "project_views", "card"):
        crumb = re.search(r'<p class="crumb">(.*?)</p>', world.anyone.get(found[kind]).text)
        assert crumb is not None, kind
        assert re.findall(r'<a href="([^"]+)"[^>]*>([^<]+)</a>', crumb[1]) == [
            ("/maintainer", "maintainer"),
            (BASE, "maity"),
        ], kind
        assert crumb[1].count("<a ") == 2 and " / " in crumb[1]
    # Current where it is the page being read.
    overview = world.anyone.get(BASE).text
    assert f'<a href="{BASE}" aria-current="page">maity</a>' in overview
    board = re.search(r'<p class="crumb">(.*?)</p>', world.anyone.get(f"{BASE}/board").text)
    assert board is not None and "aria-current" not in board[1]
    # What is stored carries the new format, so a row rendered before is rendered again.
    with world.migrated.connect() as conn:
        inputs = conn.execute(select(t.public_page.c.inputs)).scalars().all()
    assert inputs and all(public_pages.format_of(i) == public_pages.FORMAT >= 4 for i in inputs)
    # The owner's page is a stored page too, for a person (as here) and for an organisation.
    assert world.anyone.get("/maintainer").status_code == 200


def test_a_configured_landing_puts_its_nav_and_columns_in_the_served_html(world: World) -> None:
    """The frame is the landing page's, as on production: the header's section links, the
    theme switch (visible, no `hidden`: the shell has no landing.js to unhide it), and the
    footer's Platform, Open source, Legal and Follow columns. A hub with only a hero and no
    `nav_label` sections has none of those links, which is configuration, not the frame
    leaving them out (tsk-d0ktrdakakhp)."""
    path = families(world)["project"]
    html = world.anyone.get(path).text
    page = Frame(html)
    labels = [label for label, _ in page.header]
    assert labels[:5] == ["maity", "How it works", "For you & teams", "Open Source", "FAQ"]
    assert any(href.startswith("/login") for _, href in page.header)
    assert any(href.startswith("/register") for _, href in page.header)
    # The four section links go to the landing page, not this project's path.
    by_label = dict(page.header)
    for label, anchor in (
        ("How it works", "#s1"),
        ("For you & teams", "#s2"),
        ("Open Source", "#s3"),
        ("FAQ", "#s4"),
    ):
        assert by_label[label].endswith(anchor) and by_label[label].startswith("/"), label
    # Theme switch in the served header, visible without script (layout slot).
    header = html.split("<header ", 2)[2].split("</header>", 1)[0]  # the site-header, after the bar
    assert 'class="theme-toggle"' in header and "data-lp-theme" in header
    assert " hidden" not in header and "hidden " not in header.split("theme-toggle", 1)[1][:80]
    # Footer columns as production has them.
    foot = html.split('<footer id="site-footer"', 1)[1].split("</footer>", 1)[0]
    for title in ("Platform", "Open source", "Legal", "Follow"):
        assert f'aria-label="{title}"' in foot, title
    assert "How it works" in foot and "GitHub" in foot and "Imprint" in foot
    assert "https://x.com/maityteam" in foot and "Oliver Zehentleitner" in foot
    # The same links as `/explore` (the hub-framed page), left out the theme switch.
    explore = Frame(world.anyone.get("/explore").text, served=False)
    assert [label for label, _ in page.header] == [label for label, _ in explore.header]
    assert unbased(page.footer, path) == explore.footer
