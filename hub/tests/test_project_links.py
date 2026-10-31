"""docs/api.md §6.11, "The project's own links", and §16.9: `links` on a project,
validation, merge semantics, events and the public project page."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import project_links, public_pages
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory


def fields(response: Any) -> dict[str, str]:
    found: dict[str, str] = response.json()["error"]["details"]["fields"]
    return found


def pages(make_client: ClientFactory) -> ClientFactory:
    return lambda **kw: make_client(public_pages=True, **kw)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(pages(make_client), migrated)
    flow.project(human)
    return human


def test_validation_of_valid_and_invalid_urls() -> None:
    # Valid https URLs on any DNS host
    for url in (
        "https://github.com/org/repo/issues",
        "https://gitlab.com/org/repo/-/wikis/home",
        "https://discord.gg/abc1234",
        "https://t.me/my_group",
        "https://matrix.to/#/#myroom:matrix.org",
        "https://sub.domain.example.co.uk/path?q=1#frag",
    ):
        assert project_links.link_problem(url) is None

    # Invalid URLs
    assert project_links.link_problem("http://github.com/issues") == "format"  # http
    assert project_links.link_problem("https://localhost/issues") == "format"  # localhost
    assert project_links.link_problem("https://127.0.0.1/issues") == "format"  # IPv4
    assert project_links.link_problem("https://[::1]/issues") == "format"  # IPv6
    assert project_links.link_problem("https://user:pass@example.com/i") == "format"  # userinfo
    assert project_links.link_problem("https://example.com:8443/i") == "format"  # port
    assert project_links.link_problem("https://example.com/a b") == "format"  # whitespace
    assert project_links.link_problem("https://example.com/\x01") == "format"  # control char
    assert project_links.link_problem("not a url") == "format"
    # Too long
    assert project_links.link_problem("https://example.com/" + "a" * 481) == "too_long"


def test_merge_semantics_and_error_fields() -> None:
    # links: null clears all
    assert project_links.checked(None, {"issues": "https://example.com/i"}) == {}

    # non-dict
    with pytest.raises(Exception) as exc:
        project_links.checked("not-a-dict", None)
    assert exc.value.details["fields"] == {"links": "format"}  # type: ignore[attr-defined]

    # unknown key
    with pytest.raises(Exception) as exc:
        project_links.checked({"foo": "https://example.com/i"}, None)
    assert exc.value.details["fields"] == {"links.foo": "unknown"}  # type: ignore[attr-defined]

    # format & too_long & unknown keys together
    with pytest.raises(Exception) as exc:
        project_links.checked(
            {
                "issues": "http://bad.org",
                "wiki": "https://example.com/" + "w" * 490,
                "chat": 123,
                "extra": "https://example.com",
            },
            None,
        )
    assert exc.value.details["fields"] == {  # type: ignore[attr-defined]
        "links.issues": "format",
        "links.wiki": "too_long",
        "links.chat": "format",
        "links.extra": "unknown",
    }

    # partial update & null clearing
    initial = {"issues": "https://example.com/i", "wiki": "https://example.com/w"}
    # wiki null clears it, chat set, issues left out stays
    updated = project_links.checked(
        {"wiki": None, "chat": "https://discord.gg/invite"},
        initial,
    )
    assert updated == {
        "issues": "https://example.com/i",
        "chat": "https://discord.gg/invite",
    }


def test_view_always_has_four_keys() -> None:
    assert project_links.view(None) == {
        "issues": None,
        "wiki": None,
        "discussions": None,
        "chat": None,
    }
    assert project_links.view({"issues": "https://example.com/i"}) == {
        "issues": "https://example.com/i",
        "wiki": None,
        "discussions": None,
        "chat": None,
    }


def test_is_under_repository_and_public_page_visibility() -> None:
    repo = "https://github.com/owner/project"

    # Link under repository path
    assert (
        project_links.is_under_repository("https://github.com/owner/project/issues", repo) is True
    )
    assert project_links.is_under_repository("https://github.com/owner/project/wiki", repo) is True
    # Link on same host but not under repo path
    assert (
        project_links.is_under_repository("https://github.com/other/project/issues", repo) is False
    )
    assert (
        project_links.is_under_repository("https://github.com/owner/project-extra", repo) is False
    )
    # Compared without case and segment by segment (§16.9, #840)
    assert (
        project_links.is_under_repository("https://GITHUB.COM/Owner/Project/Issues", repo) is True
    )
    assert (
        project_links.is_under_repository("https://github.com/owner/project/WIKI/Page", repo)
        is True
    )
    # Link on different host
    assert project_links.is_under_repository("https://discord.gg/abc", repo) is False

    # Visibility when repository is public (True)
    assert (
        project_links.link_visible_on_public_page(
            "https://github.com/owner/project/issues", repo, True
        )
        is True
    )
    assert project_links.link_visible_on_public_page("https://discord.gg/abc", repo, True) is True

    # Visibility when repository is private (False or None)
    assert (
        project_links.link_visible_on_public_page(
            "https://github.com/owner/project/issues", repo, False
        )
        is False
    )
    assert (
        project_links.link_visible_on_public_page(
            "https://github.com/owner/project/issues", repo, None
        )
        is False
    )
    # Outside links stay visible even when repo is private
    assert project_links.link_visible_on_public_page("https://discord.gg/abc", repo, False) is True
    assert project_links.link_visible_on_public_page("https://discord.gg/abc", repo, None) is True


def test_patch_project_links_and_events(owner: flow.Human, migrated: Engine) -> None:
    # Initially links are all null
    p = owner.get("/projects/maintainer/maity").json()
    assert p["links"] == {
        "issues": None,
        "wiki": None,
        "discussions": None,
        "chat": None,
    }

    # Invalid payload
    bad = owner.patch("/projects/maintainer/maity", {"links": "not-a-dict"})
    assert bad.status_code == 400
    assert fields(bad) == {"links": "format"}

    bad_field = owner.patch(
        "/projects/maintainer/maity", {"links": {"issues": "http://insecure.org", "foo": "bar"}}
    )
    assert bad_field.status_code == 400
    assert fields(bad_field) == {"links.issues": "format", "links.foo": "unknown"}

    # Set links
    res = owner.patch(
        "/projects/maintainer/maity",
        {
            "links": {
                "issues": "https://github.com/maintainer/maity/issues",
                "chat": "https://discord.gg/maity",
            }
        },
    )
    assert res.status_code == 200
    assert res.json()["links"] == {
        "issues": "https://github.com/maintainer/maity/issues",
        "wiki": None,
        "discussions": None,
        "chat": "https://discord.gg/maity",
    }

    # Verify event emitted
    with migrated.connect() as conn:
        events = [
            e.payload
            for e in conn.execute(
                select(t.event).where(t.event.c.kind == "project_updated").order_by(t.event.c.seq)
            )
        ]
    link_events = [e for e in events if e.get("fields") == ["links"]]
    assert len(link_events) == 1

    # Merge update: clear issues, set wiki, leave chat
    res2 = owner.patch(
        "/projects/maintainer/maity",
        {
            "links": {
                "issues": None,
                "wiki": "https://github.com/maintainer/maity/wiki",
            }
        },
    )
    assert res2.status_code == 200
    assert res2.json()["links"] == {
        "issues": None,
        "wiki": "https://github.com/maintainer/maity/wiki",
        "discussions": None,
        "chat": "https://discord.gg/maity",
    }

    # links: null clears all four
    res3 = owner.patch("/projects/maintainer/maity", {"links": None})
    assert res3.status_code == 200
    assert res3.json()["links"] == {
        "issues": None,
        "wiki": None,
        "discussions": None,
        "chat": None,
    }


def test_public_project_page_renders_links(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    # Configure project with repository and turn public page on
    owner.patch(
        "/projects/maintainer/maity",
        {
            "public_page": "on",
            "repository": {"url": "https://github.com/maintainer/maity"},
            "links": {
                "issues": "https://github.com/maintainer/maity/issues",
                "chat": "https://discord.gg/maity",
            },
        },
    )

    with migrated.connect() as conn:
        page = public_pages.get(conn, "/maintainer/maity")
    assert page is not None
    # Initially repository_public is None (private): forge link inside repo path is HIDDEN
    assert "https://github.com/maintainer/maity/issues" not in page.body
    # But outside chat link is SHOWN with rel="nofollow ugc"
    assert (
        '<a href="https://discord.gg/maity" rel="nofollow ugc">https://discord.gg/maity</a>'
        in page.body
    )

    # Now simulate probe reporting repository is public
    with migrated.begin() as conn:
        conn.execute(
            t.project.update().where(t.project.c.slug == "maity").values(repository_public=True)
        )
        # Touch to re-render
        from maity_hub import public_projects

        project_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
        public_pages.touch(conn, public_projects.KIND, project_id)

    with migrated.connect() as conn:
        page2 = public_pages.get(conn, "/maintainer/maity")
    assert page2 is not None
    # Now issues link IS SHOWN
    assert (
        '<a href="https://github.com/maintainer/maity/issues" rel="nofollow ugc">https://github.com/maintainer/maity/issues</a>'
        in page2.body
    )
    assert (
        '<a href="https://discord.gg/maity" rel="nofollow ugc">https://discord.gg/maity</a>'
        in page2.body
    )
