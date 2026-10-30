"""docs/api.md §16.9, "A person's links": `website`, `social` and `links_visible` of
`PATCH /me`, who sees them, and the person's page."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


def patch(who: flow.Human, **body: Any) -> Any:
    return who.patch("/me", body)


def own(who: flow.Human) -> dict[str, Any]:
    member: dict[str, Any] = who.get("/me").json()["member"]
    return member


def fields(response: Any) -> dict[str, str]:
    found: dict[str, str] = response.json()["error"]["details"]["fields"]
    return found


@pytest.fixture
def person(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def test_a_person_has_no_links_and_keeps_them_to_themselves(person: flow.Human) -> None:
    member = own(person)
    assert (member["website"], member["social"], member["links_visible"]) == (None, {}, "private")


@pytest.mark.parametrize(
    ("network", "name", "stored"),
    [
        ("github", "octo-cat", "octo-cat"),
        ("github", "a", "a"),
        ("gitlab", "some.user_1", "some.user_1"),
        ("x", "oz_agent", "oz_agent"),
        ("mastodon", "@oz@Mastodon.Example", "@oz@mastodon.example"),
        ("bluesky", "Oz.Bsky.Social", "oz.bsky.social"),
        ("bluesky", "did:plc:" + "a2" * 12, "did:plc:" + "a2" * 12),
        ("linkedin", "oz-agent-1", "oz-agent-1"),
        ("discord", "oz.agent_1", "oz.agent_1"),
    ],
)
def test_a_name_of_its_form_is_stored_and_two_hosts_are_lower_cased(
    person: flow.Human, network: str, name: str, stored: str
) -> None:
    done = patch(person, social={network: name})
    assert done.status_code == 200, done.text
    assert done.json()["member"]["social"] == {network: stored}


@pytest.mark.parametrize(
    ("network", "name"),
    [
        ("github", "-bad"),
        ("github", "bad-"),
        ("github", "a" * 40),
        ("github", "has space"),
        ("github", "@octo"),
        ("gitlab", "repo.git"),
        ("gitlab", "feed.atom"),
        ("gitlab", "repo.GIT"),
        ("gitlab", "feed.Atom"),
        ("gitlab", ".dot"),
        ("x", "sixteen_chars_xx"),
        ("x", "dash-ed"),
        ("mastodon", "oz@mastodon.example"),
        ("mastodon", "@oz@localhost"),
        ("mastodon", "@oz@1.2.3.4"),
        ("mastodon", "@oz@host.example:8080"),
        ("mastodon", "@oz@host.example/path"),
        ("mastodon", "@@host.example"),
        ("bluesky", "nodots"),
        ("bluesky", "1.2.3.4"),
        ("bluesky", "did:plc:short"),
        ("bluesky", "did:web:example.org"),
        ("linkedin", "ab"),
        ("linkedin", "has_underscore"),
        ("discord", "A"),
        ("discord", "UPPER"),
    ],
)
def test_a_name_that_is_not_of_its_form_is_invalid(
    person: flow.Human, network: str, name: str
) -> None:
    refused = patch(person, social={network: name})
    assert refused.status_code == 400, refused.text
    assert fields(refused) == {f"social.{network}": "format"}
    assert own(person)["social"] == {}


def test_an_unknown_network_and_a_social_that_is_no_object_are_invalid(person: flow.Human) -> None:
    refused = patch(person, social={"myspace": "tom", "github": "ok"})
    assert fields(refused) == {"social.myspace": "unknown"}
    assert own(person)["social"] == {}  # all or nothing
    for not_an_object in ("github", ["github"], 3):
        assert fields(patch(person, social=not_an_object)) == {"social": "format"}


def test_a_null_social_clears_every_network(person: flow.Human) -> None:
    patch(person, social={"github": "octo", "x": "oz"})
    done = patch(person, social=None)
    assert done.status_code == 200, done.text
    assert done.json()["member"]["social"] == {}


def test_social_merges_by_network_and_a_null_clears_one(person: flow.Human) -> None:
    patch(person, social={"github": "octo", "x": "oz"})
    done = patch(person, social={"github": "octo2", "discord": "oz.d"})
    assert done.json()["member"]["social"] == {"github": "octo2", "x": "oz", "discord": "oz.d"}
    cleared = patch(person, social={"x": None, "discord": ""})
    assert cleared.json()["member"]["social"] == {"github": "octo2"}
    assert patch(person, social={"github": None}).json()["member"]["social"] == {}


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org",
        "https://example.org/path?q=1",
        "https://sub.example.org/x",
    ],
)
def test_a_website_is_an_https_url(person: flow.Human, url: str) -> None:
    done = patch(person, website=url)
    assert done.status_code == 200, done.text
    assert done.json()["member"]["website"] == url
    assert patch(person, website=None).json()["member"]["website"] is None


@pytest.mark.parametrize(
    ("url", "problem"),
    [
        ("http://example.org", "format"),
        ("//example.org", "format"),
        ("example.org", "format"),
        ("https://user:pw@example.org", "format"),
        ("https://user@example.org", "format"),
        ("https://exa mple.org", "format"),
        ("https://example.org/\n", "format"),
        ("https://example.org:99999", "format"),
        ("https://example.org:8443/x", "format"),
        ("https://example.org:/x", "format"),
        ("https://localhost", "format"),
        ("https://127.0.0.1/", "format"),
        ("https://[::1]/", "format"),
        ("https://example.org./", "format"),
        ("https://" + "a" * 190 + ".org", "too_long"),
    ],
)
def test_a_website_that_is_no_https_url_is_invalid(
    person: flow.Human, url: str, problem: str
) -> None:
    refused = patch(person, website=url)
    assert refused.status_code == 400, refused.text
    assert fields(refused) == {"website": problem}


def test_links_visible_takes_five_values_and_refuses_the_rest(person: flow.Human) -> None:
    for value in ("private", "friends", "colleagues", "friends_and_colleagues", "everyone"):
        assert patch(person, links_visible=value).json()["member"]["links_visible"] == value
    refused = patch(person, links_visible="world")
    assert fields(refused) == {"links_visible": "unknown"}
    assert fields(patch(person, links_visible=None)) == {"links_visible": "unknown"}


def test_an_agent_sets_none_of_the_fields(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    bot = flow.agent(make_client, owner, role="admin")
    for body in (
        {"website": "https://example.org"},
        {"social": {"x": "a"}},
        {"links_visible": "everyone"},
    ):
        refused = bot.patch("/me", body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"]["reason"] == "humans_only"


def member_of(reader: Any, handle: str = "maintainer") -> dict[str, Any]:
    items = reader.get("/projects/maintainer/maity/members").json()["items"]
    found: dict[str, Any] = next(m for m in items if m["handle"] == handle)
    return found


@pytest.mark.parametrize(
    ("value", "self_sees", "colleague_sees", "agent_sees"),
    [
        ("private", True, False, False),
        ("friends", True, False, False),  # follow does not exist: nobody
        ("colleagues", True, True, False),  # agents never
        ("friends_and_colleagues", True, True, False),
        ("everyone", True, True, True),
    ],
)
def test_each_value_admits_its_readers_in_the_member_views(
    make_client: ClientFactory,
    migrated: Engine,
    value: str,
    self_sees: bool,
    colleague_sees: bool,
    agent_sees: bool,
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    colleague = flow.human(make_client, migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=colleague.id)
    bot = flow.agent(make_client, owner, role="coder")
    patch(owner, website="https://example.org", social={"github": "octo", "discord": "oz.d"})
    patch(owner, links_visible=value)
    expected = {
        "website": "https://example.org",
        "social": {"github": "https://github.com/octo", "discord": "oz.d"},
    }
    for reader, sees in ((owner, self_sees), (colleague, colleague_sees), (bot, agent_sees)):
        view = member_of(reader)
        assert ("website" in view) == sees and ("social" in view) == sees, (value, reader.id)
        if sees:
            assert {"website": view["website"], "social": view["social"]} == expected
    single = colleague.get(f"/projects/maintainer/maity/members/{owner.id}").json()
    assert ("website" in single) == colleague_sees


def test_the_links_are_built_from_the_names(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    patch(
        owner,
        social={
            "github": "octo",
            "gitlab": "lab.user",
            "x": "oz_x",
            "mastodon": "@oz@social.example",
            "bluesky": "oz.bsky.social",
            "linkedin": "oz-li",
            "discord": "oz.d",
        },
        links_visible="everyone",
    )
    assert member_of(owner)["social"] == {
        "github": "https://github.com/octo",
        "gitlab": "https://gitlab.com/lab.user",
        "x": "https://x.com/oz_x",
        "mastodon": "https://social.example/@oz",
        "bluesky": "https://bsky.app/profile/oz.bsky.social",
        "linkedin": "https://www.linkedin.com/in/oz-li",
        "discord": "oz.d",  # no public profile address: the name, as text
    }


def test_a_change_is_announced_without_the_links(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    patch(owner, website="https://example.org")
    patch(owner, links_visible="everyone")
    with migrated.connect() as conn:
        payloads = [
            e.payload
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload.get("changed") == ["links"]
        ]
    assert len(payloads) == 2
    for payload in payloads:
        assert (
            "website" not in payload and "social" not in payload
        )  # who reads depends on the reader
        assert payload["id"] == owner.id


def test_the_person_page_shows_the_links_under_everyone_only(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated)
    anyone = make_client(public_pages=True)
    patch(who, public_profile=True)
    patch(who, website="https://example.org/me", social={"github": "octo", "discord": "oz.d"})
    assert "example.org" not in anyone.get("/maintainer").text  # private by default
    patch(who, links_visible="colleagues")
    assert "example.org" not in anyone.get("/maintainer").text
    patch(who, links_visible="everyone")
    text = anyone.get("/maintainer").text
    assert '<a href="https://example.org/me" rel="me nofollow">https://example.org/me</a>' in text
    assert '<a href="https://github.com/octo" rel="me nofollow">octo</a>' in text
    assert "<li>discord: oz.d</li>" in text and "https://discord" not in text
    # off again: gone at once
    patch(who, links_visible="private")
    assert "example.org" not in anyone.get("/maintainer").text


def test_a_hold_on_the_profile_makes_everyone_act_as_colleagues(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    anna = flow.human(make_client, migrated, "anna")
    ben = flow.human(make_client, migrated, "ben")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    for human in (anna, ben):
        factory.membership(migrated, project_id, "member", human_id=human.id)
    bot = flow.agent(make_client, owner, role="coder")
    patch(anna, website="https://example.org", links_visible="everyone")
    for reader in (ben, bot, anna):
        assert "website" in member_of(reader, "anna")
    made = owner.post("/reports", {"target": {"type": "profile", "id": anna.id}, "reason": "spam"})
    assert made.status_code == 201, made.text
    held = owner.post(f"/admin/reports/{made.json()['id']}/resolve", {"action": "hide"})
    assert held.status_code == 200, held.text
    assert "website" in member_of(ben, "anna")  # a colleague still reads it
    assert "website" not in member_of(bot, "anna")  # the world does not
    assert "website" in member_of(anna, "anna")  # nor does the person lose their own


def test_an_edit_that_stores_what_was_there_is_not_announced(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    patch(owner, links_visible="everyone", social={"github": "octo"})
    patch(owner, links_visible="everyone", social={"github": "octo"})
    patch(owner, website=None)
    with migrated.connect() as conn:
        announced = [
            e
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload.get("changed") == ["links"]
        ]
    assert len(announced) == 1
