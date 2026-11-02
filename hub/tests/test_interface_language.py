"""A person's two languages (docs/api.md §6.2, §2.7.1): the interface language for the portal and
the hub's own texts, `language` for what agents write."""

from __future__ import annotations

import re
from collections.abc import Callable

from sqlalchemy import Engine, select

from maity_hub import catalog, events, languages
from maity_hub import tables as t
from maity_hub.landing import LANGUAGES
from tests import flow
from tests.conftest import ClientFactory
from tests.test_human_language import S
from tests.test_notification_mail import ask, notifications, run, setup
from tests.test_notification_mail import at as at  # noqa: F401  (the clock fixture)
from tests.test_register_page import answer, hub, humans, pending, start
from tests.test_registration import PASSWORD
from tests.test_team_rules import _membership, _Reader


def test_the_list_marks_what_a_person_is_offered(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    items = {i["tag"]: i for i in owner.get("/languages").json()["items"]}
    assert {tag for tag, i in items.items() if i["interface"]} == set(LANGUAGES)
    assert {tag for tag, i in items.items() if i["common"]} == languages.COMMON
    assert set(items) >= languages.COMMON and set(LANGUAGES) <= languages.COMMON
    assert not items["ae"]["common"]  # still accepted, not offered


def test_a_person_chooses_the_interface_language_and_clears_it(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.get("/me").json()["member"]["interface_language"] is None
    done = owner.patch("/me", {"interface_language": "ja"})
    assert done.status_code == 200 and done.json()["member"]["interface_language"] == "ja"
    assert owner.get("/auth/session").json()["member"]["interface_language"] == "ja"
    assert owner.patch("/me", {"interface_language": None}).status_code == 200
    assert owner.get("/me").json()["member"]["interface_language"] is None


def test_the_interface_language_is_one_of_the_ten_and_a_humans_own(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    refused = owner.patch("/me", {"interface_language": "sw"})  # agents may write in it
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"]["interface_language"] == "unknown_language"
    assert agent.patch("/me", {"interface_language": "de"}).status_code == 403
    assert owner.patch("/me", {"interface_language": "de"}).status_code == 200
    listed = {m["id"]: m for m in agent.get("/projects/maintainer/maity/members").json()["items"]}
    assert "interface_language" not in listed[owner.id]


def test_the_mail_follows_the_interface_language_not_the_one_agents_write_in(
    make_client: ClientFactory, migrated: Engine, at: Callable[..., None]
) -> None:
    owner, agent = setup(make_client, migrated)
    assert owner.patch(S, {"email": {"language": "sw"}}).status_code == 200
    assert owner.patch("/me", {"interface_language": "de"}).status_code == 200
    ask(agent, "Welche?")
    at(minutes=3)
    run(migrated)
    [mail] = notifications(migrated)
    assert "fragt: Welche?" in mail.subject


def test_without_a_choice_the_hub_speaks_what_agents_write_in_where_it_can(
    make_client: ClientFactory, migrated: Engine
) -> None:
    assert languages.of_interface(None, "ko") == "ko"
    assert languages.of_interface(None, "sw") == "en"
    assert languages.of_interface("de", "sw") == "de"
    assert languages.of_interface(None, None) == "en"


def test_registration_takes_both_languages_to_the_account(
    make_client: ClientFactory, migrated: Engine
) -> None:
    settings = hub()
    client, _ = start(make_client, migrated, settings)
    asked = client.post(
        "/api/v1/auth/register",
        json={
            "address": "lin@x.org",
            "password": PASSWORD,
            "interface_language": "de",
            "language": "sw",
        },
        headers={"Accept-Language": "en"},
    )
    assert asked.status_code == 202
    with migrated.connect() as conn:
        mail = conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id.desc())).first()
    assert mail is not None
    assert (
        mail.subject == catalog.section("registration_mail", "de")["confirm_subject"]
    )  # not the browser's `en`
    found = re.search(r"https://hub\.example(/mail/register/\S+)", mail.body)
    assert found
    link = found.group(1)
    page = client.get(link)
    assert '<html lang="de"' in page.text
    assert answer(client, link, page, handle="lin", display_name="Lin").status_code == 303
    me = client.get("/api/v1/me").json()["member"]
    assert me["interface_language"] == "de"
    assert client.get("/api/v1/me/notification-settings").json()["email"]["language"] == "sw"


def test_registration_without_a_choice_leaves_both_unset(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, link = start(make_client, migrated, hub(), language="de")
    row = pending(migrated)
    assert (row.interface_language, row.chosen_language) == (None, None)
    answer(client, link, client.get(link))
    [created] = humans(migrated)
    assert created.interface_language is None
    assert client.get("/api/v1/me/notification-settings").json()["email"]["language"] == "en"


def test_registration_refuses_a_language_it_does_not_know(
    make_client: ClientFactory, migrated: Engine
) -> None:
    client, _ = start(make_client, migrated, hub())
    for field, value in (("interface_language", "sw"), ("language", "xx")):
        asked = client.post(
            "/api/v1/auth/register",
            json={"address": "lin@x.org", "password": PASSWORD, field: value},
        )
        assert asked.status_code == 400, asked.text
        assert asked.json()["error"]["details"]["fields"][field] == "unknown_language"


def test_a_change_of_language_reaches_the_agents_and_wakes_nobody(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)

    def updates() -> list[object]:
        with migrated.connect() as conn:
            return list(
                conn.execute(
                    select(t.event)
                    .where(t.event.c.kind == "member_updated")
                    .order_by(t.event.c.seq)
                ).all()
            )

    before = len(updates())
    assert owner.patch(S, {"email": {"language": "en"}}).status_code == 200  # no change, no news
    assert len(updates()) == before
    assert owner.patch(S, {"email": {"language": "de"}}).status_code == 200
    [event] = updates()[before:]
    assert event.payload["changed"] == ["language"] and event.payload["language"] == "de"  # type: ignore[attr-defined]
    reader = _Reader(_membership(migrated, agent))
    assert not events.wakes(event, reader, agent.id, agent.instance)


def test_an_agent_reads_its_own_humans_language_on_me_owner(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    assert owner.patch(S, {"email": {"language": "de"}}).status_code == 200
    packet = agent.resume().json()
    assert packet["me"]["owner"]["language"] == "de"


def test_an_agent_reads_the_language_of_a_human_who_is_no_member(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    other = flow.human(make_client, migrated, handle="other")
    assert other.patch(S, {"email": {"language": "de"}}).status_code == 200
    with migrated.begin() as conn:  # its human stands outside the project
        conn.execute(
            t.agent_profile.update()
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=other.id)
        )
    assert agent.resume().json()["me"]["owner"] == {
        "id": other.id,
        "handle": "other",
        "language": "de",
        "meat_proxy": False,
    }


def test_the_export_carries_the_interface_language(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    assert owner.patch("/me", {"interface_language": "de"}).status_code == 200
    assert owner.get("/me/export").json()["account"]["interface_language"] == "de"
