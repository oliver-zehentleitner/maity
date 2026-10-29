"""docs/api.md §16.7, Search engines: /robots.txt and /sitemap.xml follow the landing page."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import middleware
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory

PUBLIC = "https://hub.example"
LEGAL = {"en": {"title": "Legal", "markdown": "Text."}}


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def enable(admin: flow.Human, enabled: bool = True) -> None:
    done = admin.client.patch(
        "/api/v1/admin/settings/landing",
        json={
            "enabled": enabled,
            "default_language": "en",
            "pages": {
                "en": {
                    "title": "Maity",
                    "description": "",
                    "sections": [
                        {"type": "text", "enabled": True, "markdown": "Bring your own agent."}
                    ],
                }
            },
        },
        headers={"X-CSRF-Token": admin.csrf},
    )
    assert done.status_code == 200, done.text


def test_robots_lets_a_crawler_read_the_landing_page_while_it_is_enabled(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    enable(admin)
    answer = make_client().get("/robots.txt")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/plain")
    lines = answer.text.splitlines()
    assert lines[0] == "User-agent: *"
    assert [line for line in lines if line.startswith("Allow:")] == ["Allow: /$"]
    assert "Disallow: /" in lines and lines.index("Disallow: /") > lines.index("Allow: /$")
    assert lines[-1] == f"Sitemap: {PUBLIC}/sitemap.xml"


def test_robots_also_allows_the_legal_pages_that_are_set(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    enable(admin)
    admin.patch("/admin/settings/legal", {"imprint": LEGAL})
    admin.patch("/admin/settings/legal", {"terms": LEGAL})
    lines = make_client().get("/robots.txt").text.splitlines()
    assert [line for line in lines if line.startswith("Allow:")] == [
        "Allow: /$",
        "Allow: /impressum$",
        "Allow: /terms$",
    ]


def test_robots_asks_for_nothing_but_the_root_while_the_landing_page_is_off(
    make_client: ClientFactory,
) -> None:
    answer = make_client().get("/robots.txt")  # off until an admin switches it on
    assert answer.status_code == 200
    assert answer.text == "User-agent: *\nAllow: /$\nDisallow: /\n"
    assert "Sitemap" not in answer.text


def test_the_sitemap_lists_exactly_the_root_with_the_pages_date(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    enable(admin)
    answer = make_client().get("/sitemap.xml")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("application/xml")
    stored = admin.get("/admin/settings/landing").json()["updated_at"]
    assert answer.text.count("<url>") == 1
    assert f"<loc>{PUBLIC}/</loc>" in answer.text
    assert f"<lastmod>{stored}</lastmod>" in answer.text
    assert answer.text.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_the_sitemap_lists_the_legal_pages_that_are_set_with_their_versions(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    enable(admin, enabled=False)
    version = admin.patch("/admin/settings/legal", {"privacy": LEGAL}).json()["pages"]["privacy"][
        "version"
    ]
    answer = make_client().get("/sitemap.xml")  # no landing page, but a legal page: a sitemap
    assert answer.status_code == 200
    assert answer.text.count("<url>") == 1
    assert f"<loc>{PUBLIC}/privacy</loc>" in answer.text
    assert f"<lastmod>{version}</lastmod>" in answer.text
    enable(admin)
    assert make_client().get("/sitemap.xml").text.count("<url>") == 2


def test_there_is_no_sitemap_while_the_landing_page_is_off(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    assert make_client().get("/sitemap.xml").status_code == 404
    enable(admin)
    enable(admin, enabled=False)
    off = make_client().get("/sitemap.xml")
    assert off.status_code == 404 and off.json()["error"]["code"] == "not_found"


def test_both_files_are_cached_for_an_hour_and_set_no_cookie(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    enable(admin)
    client = make_client()
    for path in ("/robots.txt", "/sitemap.xml"):
        answer = client.get(path)
        assert answer.headers["cache-control"] == "public, max-age=3600", path
        assert "set-cookie" not in answer.headers, path
    off = make_client().get("/api/v1/health")
    assert off.headers["cache-control"] == "no-store"  # the exception stays narrow


def test_the_shell_is_noindex_and_the_landing_page_at_the_root_is_not(
    make_client: ClientFactory, admin: flow.Human, web_dir: Any
) -> None:
    (web_dir / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    client = make_client()
    assert client.get("/").headers.get("x-robots-tag") == "noindex"
    assert client.head("/").headers.get("x-robots-tag") == "noindex"
    assert "x-robots-tag" not in client.get("/api/v1/health").headers  # only the shell
    enable(admin)
    page = client.get("/")
    assert "Bring your own agent" in page.text and "x-robots-tag" not in page.headers


def test_the_join_host_has_neither_file(make_client: ClientFactory) -> None:
    client = make_client(join_url="https://join.example")
    for path in ("/robots.txt", "/sitemap.xml"):
        answer = client.get(path, headers={"host": "join.example"}, follow_redirects=False)
        assert answer.status_code == 404, path
        assert answer.json()["error"]["code"] == "not_found"


def test_the_exception_for_the_files_is_the_files_own(settings: Settings) -> None:
    assert middleware.SEO_PATHS.fullmatch("/robots.txt") and middleware.SEO_PATHS.fullmatch(
        "/sitemap.xml"
    )
    assert not middleware.SEO_PATHS.fullmatch(
        "/robots.txt/"
    ) and not middleware.SEO_PATHS.fullmatch("/api/v1/robots.txt")
