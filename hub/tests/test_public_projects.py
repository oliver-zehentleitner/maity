"""docs/api.md §16.9: a project's public page, `public_page` and `public_about` of
`PATCH /projects/{owner}/{slug}`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, public_pages, public_projects
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_moderation import resolve
from tests.test_reports import report
from tests.test_reports import team as team  # noqa: F401  (the fixture)
from tests.test_two_factor import moment as moment  # noqa: F401  (the clock fixture)

PATH = "/maintainer/maity"


def pages(make_client: ClientFactory) -> ClientFactory:
    return lambda **kw: make_client(public_pages=True, **kw)


def visitor(make_client: ClientFactory) -> Any:
    return make_client(public_pages=True)


def shown(client: Any, path: str = PATH) -> str | None:
    got = client.get(path)
    assert got.status_code == 200
    return None if "<title>dashboard</title>" in got.text else str(got.text)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(pages(make_client), migrated)
    flow.project(human)
    return human


def test_a_project_is_private_until_its_owner_turns_the_page_on(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    view = owner.get("/projects/maintainer/maity").json()
    assert (view["public_page"], view["public_about"]) == ("off", None)
    assert shown(visitor(make_client)) is None


def test_turning_the_page_on_publishes_it_and_off_takes_it_away_at_once(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    anyone = visitor(make_client)
    got = owner.patch(
        "/projects/maintainer/maity",
        {
            "public_page": "on",
            "public_about": "We build **agents**. See [docs](https://example.org/d).",
        },
    )
    assert got.status_code == 200, got.text
    assert (got.json()["public_page"], got.json()["public_about"]) == (
        "on",
        "We build **agents**. See [docs](https://example.org/d).",
    )
    text = shown(anyone)
    assert text is not None
    assert "<h1>Maity</h1>" in text and "maintainer/maity" in text and "build" in text
    assert "<strong>agents</strong>" in text and 'rel="nofollow ugc"' in text
    assert '<link rel="canonical" href="https://hub.example/maintainer/maity">' in text
    assert "<script" not in text
    assert owner.patch("/projects/maintainer/maity", {"public_page": "off"}).status_code == 200
    assert shown(anyone) is None
    # the text stays the owner's, and the page comes back with the switch
    assert owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    assert shown(anyone) is not None


def test_the_event_names_the_fields_and_never_the_text(owner: flow.Human, migrated: Engine) -> None:
    owner.patch(
        "/projects/maintainer/maity", {"public_page": "on", "public_about": "secret-ish words"}
    )
    with migrated.connect() as conn:
        events = [
            e.payload
            for e in conn.execute(select(t.event).where(t.event.c.kind == "project_updated"))
        ]
    fields = [p["fields"] for p in events if "public_page" in p["fields"]]
    assert fields == [{"public_page": "on", "public_about": True}]
    assert "secret-ish" not in str(events)


def test_editing_the_text_renders_the_page_again(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    anyone = visitor(make_client)
    owner.patch("/projects/maintainer/maity", {"public_page": "on", "public_about": "first"})
    first = anyone.get(PATH)
    owner.patch("/projects/maintainer/maity", {"public_about": "second"})
    second = anyone.get(PATH)
    assert "first" not in second.text and "second" in second.text
    assert second.headers["etag"] != first.headers["etag"]
    owner.patch("/projects/maintainer/maity", {"public_about": None})
    assert "second" not in anyone.get(PATH).text
    assert owner.get("/projects/maintainer/maity").json()["public_about"] is None


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("x" * 4097, "too_long"),
        ("é" * 2049, "too_long"),  # bytes, not characters
        ("a <script>alert(1)</script>", "line 1"),
        ("fine\n![an image](https://example.org/i.png)", "line 2"),
        ("a [link](javascript:alert(1))", "line 1"),
    ],
)
def test_a_text_the_markdown_rules_refuse_is_invalid(
    owner: flow.Human, text: str, problem: str
) -> None:
    refused = owner.patch("/projects/maintainer/maity", {"public_about": text})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"public_about": problem}


def test_a_text_of_4_kib_is_fine(owner: flow.Human) -> None:
    assert (
        owner.patch("/projects/maintainer/maity", {"public_about": "x" * 4096}).status_code == 200
    )


def test_only_the_namespace_owner_a_human_sets_it(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    admin = flow.human(make_client, migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    refused = admin.patch("/projects/maintainer/maity", {"public_page": "on"})
    assert refused.status_code == 403, refused.text
    bot = flow.agent(make_client, owner, role="admin")
    agent_refused = bot.patch("/projects/maintainer/maity", {"public_page": "on"})
    assert agent_refused.status_code == 403, agent_refused.text
    assert owner.get("/projects/maintainer/maity").json()["public_page"] == "off"


def test_a_value_that_is_no_choice_and_a_null_switch_are_refused(owner: flow.Human) -> None:
    assert owner.patch("/projects/maintainer/maity", {"public_page": "maybe"}).status_code == 400
    assert owner.patch("/projects/maintainer/maity", {"public_page": None}).status_code == 400


def test_an_archived_project_has_no_page_and_gets_it_back_when_it_is_reopened(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    anyone = visitor(make_client)
    owner.patch("/projects/maintainer/maity", {"public_page": "on"})
    archived = owner.patch("/projects/maintainer/maity", {"state": "archived", "reason": "done"})
    assert archived.status_code == 200, archived.text
    assert shown(anyone) is None
    reopened = owner.patch("/projects/maintainer/maity", {"state": "build", "reason": "again"})
    assert reopened.status_code == 200, reopened.text
    assert shown(anyone) is not None


def test_a_rename_moves_the_page_and_the_old_address_is_the_shell(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    anyone = visitor(make_client)
    owner.patch("/projects/maintainer/maity", {"public_page": "on"})
    renamed = owner.patch("/projects/maintainer/maity", {"slug": "hive", "reason": "new name"})
    assert renamed.status_code == 200, renamed.text
    assert shown(anyone, "/maintainer/hive") is not None
    assert shown(anyone, PATH) is None  # no redirect, no page under the old name (§16.9)
    anyone_get = anyone.get(PATH, follow_redirects=False)
    assert anyone_get.status_code == 200


def test_a_transfer_turns_the_page_off_and_the_consent_request_says_so(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    anyone = visitor(make_client)
    anna = flow.human(pages(make_client), migrated, "anna")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "owner", human_id=anna.id)
    owner.patch("/projects/maintainer/maity", {"public_page": "on"})
    assert shown(anyone) is not None
    filed = owner.post("/projects/maintainer/maity/transfer", {"to": anna.id})
    assert filed.status_code == 202, filed.text
    assert "public page is turned off by the move" in filed.json()["summary"]
    done = anna.post(
        f"/projects/maintainer/maity/requests/{filed.json()['id']}/answer", {"reply_id": "go"}
    )
    assert done.status_code == 200, done.text
    assert anna.get("/projects/anna/maity").json()["public_page"] == "off"
    assert shown(anyone, "/anna/maity") is None and shown(anyone) is None


def test_a_hidden_project_has_no_page_and_cannot_be_made_public_again_until_the_hold_goes(
    team: dict[str, Any], migrated: Engine
) -> None:
    boss = team["owner"]
    assert boss.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    made = report(team["pat"], {"type": "project", "id": "maintainer/maity"}, "spam").json()
    assert resolve(team, made["id"], "hide").status_code == 200
    with migrated.connect() as conn:
        assert public_pages.get(conn, "/maintainer/maity") is None
    assert boss.patch("/projects/maintainer/maity", {"public_page": "off"}).status_code == 200
    refused = boss.patch("/projects/maintainer/maity", {"public_page": "on"})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "moderation_hold"
    assert resolve(team, made["id"], "dismiss").status_code == 200
    assert boss.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200


def test_a_project_of_a_suspended_owner_has_no_page(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human, settings: Any
) -> None:
    from maity_hub import moderation

    anyone = visitor(make_client)
    owner.patch("/projects/maintainer/maity", {"public_page": "on"})
    assert shown(anyone) is not None
    with migrated.begin() as conn:
        conn.execute(update(t.human).values(suspended_at=clock.now(), suspended_report="x"))
        public_pages.configure(replace(settings, public_pages=True))
        public_projects.touch_owned(conn, owner.id)
    assert shown(anyone) is None
    with migrated.begin() as conn:
        assert moderation.unsuspend(conn, owner.id) is True
    assert shown(anyone) is not None


def test_only_projects_with_the_switch_on_are_targets(migrated: Engine, owner: flow.Human) -> None:
    owner.post("/projects", {"slug": "second", "name": "Second"})
    owner.patch("/projects/maintainer/second", {"public_page": "on"})
    with migrated.connect() as conn:
        found = public_projects.targets(conn)
        second = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "second")
        ).scalar_one()
    assert found == [second]


def test_any_owner_of_an_organisation_sets_the_page_of_its_project_and_a_suspension_takes_it_away(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from tests.test_orgs import add_member, make_org

    admin = flow.human(pages(make_client), migrated)
    boss = flow.human(pages(make_client), migrated, "boss")
    second = flow.human(pages(make_client), migrated, "second")
    org = make_org(boss, "oz-team", "OZ Team")
    add_member(migrated, org["id"], second.id, "owner")
    assert (
        boss.post("/projects", {"slug": "shop", "name": "Shop", "owner": "oz-team"}).status_code
        == 201
    )
    anyone = visitor(make_client)
    # the second owner is a member of the project (the hub keeps the owners), and sets the page
    on = second.patch("/projects/oz-team/shop", {"public_page": "on", "public_about": "Our shop."})
    assert on.status_code == 200, on.text
    text = shown(anyone, "/oz-team/shop")
    assert text is not None and "Our shop." in text and "oz-team/shop" in text
    # a suspension of the organisation archives the project and holds the organisation
    pat = flow.human(pages(make_client), migrated, "pat")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=pat.id)
    made = report(pat, {"type": "project", "id": "oz-team/shop"}, "spam")
    assert made.status_code == 201, made.text
    assert (
        admin.post(f"/admin/reports/{made.json()['id']}/resolve", {"action": "suspend"}).status_code
        == 200
    )
    assert shown(anyone, "/oz-team/shop") is None
