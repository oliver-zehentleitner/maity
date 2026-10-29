"""docs/api.md §2.9: `GET /me/export`, a human's own data as one JSON document."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.routes import me
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def colleague(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> flow.Human:
    colleague = flow.human(make_client, migrated, "colleague")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    factory.membership(migrated, project_id, "member", human_id=colleague.id)
    return colleague


def export(who: flow.Human) -> Any:
    me.EXPORTS.reset()  # each test reads several exports; the limit has its own test
    response = who.get("/me/export")
    assert response.status_code == 200, response.text
    return response


def created(response: Any) -> dict[str, Any]:
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def say(who: Any, body: str, **extra: Any) -> dict[str, Any]:
    message = {"kind": "message", "type": "notice", "to": "all", "body": body, **extra}
    return created(who.post(f"{PROJECT}/events", message))


def card(who: Any, title: str, body: str | None = None) -> dict[str, Any]:
    return created(who.post(f"{PROJECT}/tasks", {"title": title, "body": body}))


def note(who: Any, card_id: str, body: str) -> dict[str, Any]:
    return created(who.post(f"{PROJECT}/tasks/{card_id}/notes", {"body": body}))


def test_one_document_to_save(owner: flow.Human) -> None:
    response = export(owner)
    today = clock.now().date().isoformat()
    assert response.headers["content-disposition"] == (
        f'attachment; filename="maity-export-maintainer-{today}.json"'
    )
    body = response.json()
    assert body["format"] == 1
    assert body["exported_at"]
    assert set(body) == {
        "format",
        "exported_at",
        "account",
        "sessions",
        "second_factor",
        "forge_links",
        "runners",
        "agent_profiles",
        "memberships",
        "messages",
        "chat_messages",
        "requests_asked",
        "answers_given",
        "cards_created",
        "card_reports",
        "card_notes",
        "jour_fixe_answers",
    }
    account = body["account"]
    assert (account["handle"], account["id"]) == ("maintainer", owner.id)
    assert {"display_name", "avatar_url", "addresses", "terms", "preferences"} <= set(account)
    assert set(account["notification_settings"]) == {"browser", "email"}
    assert [m["project"] for m in body["memberships"]] == ["maintainer/maity"]
    membership = body["memberships"][0]
    assert (membership["trust"], membership["left_at"]) == ("owner", None)
    [session] = body["sessions"]
    assert session["method"] and session["created_at"] and session["last_seen_at"]
    assert set(session["device"]) == {"browser", "os"}


def test_an_agent_is_refused(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.get("/me/export")
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"


def test_once_in_ten_minutes(owner: flow.Human) -> None:
    export(owner)
    again = owner.get("/me/export")
    assert again.status_code == 429
    assert again.json()["error"]["code"] == "rate_limited"
    assert 0 < int(again.headers["Retry-After"]) <= 600


def test_no_secret_in_it(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    agent = flow.agent(make_client, owner)
    body = export(owner).text
    with migrated.connect() as conn:
        human = conn.execute(select(t.human).where(t.human.c.id == owner.id)).one()
        sessions = conn.execute(
            select(t.human_session).where(t.human_session.c.human_id == owner.id)
        ).all()
        verifiers = conn.execute(select(t.credential.c.verifier)).scalars().all()
        joins = conn.execute(select(t.join_link.c.token_hash, t.join_link.c.code_hash)).all()
    secrets = [human.password_hash, agent.credential, owner.csrf, *verifiers]
    secrets += [s.id_hash for s in sessions] + [s.csrf_token for s in sessions]
    secrets += [value for row in joins for value in row]
    cookies = [c.value for c in owner.client.cookies.jar]
    for secret in secrets + cookies:
        assert secret and secret not in body
    assert "password_hash" not in body and "verifier" not in body
    # The agent profile is there, with its membership, without its credential.
    [profile] = export(owner).json()["agent_profiles"]
    assert profile["id"] == agent.id
    assert [m["project"] for m in profile["memberships"]] == ["maintainer/maity"]


def test_what_they_wrote(owner: flow.Human, colleague: flow.Human) -> None:
    mine = card(colleague, "Colleague's card", "Colleague's body")
    theirs = card(owner, "Owner's card", "Owner's secret plan")
    message = say(colleague, "Hello from the colleague", task_id=theirs["id"])
    written = note(colleague, theirs["id"], "A note by the colleague")
    asked = created(
        colleague.post(f"{PROJECT}/requests", {"class": "decision", "title": "Ship it?"})
    )
    answered = owner.post(
        f"{PROJECT}/requests/{asked['id']}/answer", {"text": "Yes, the owner says ship"}
    )
    assert answered.status_code == 200, answered.text
    say(owner, "The owner's own words")

    response = export(colleague)
    body = response.json()
    [sent] = body["messages"]
    assert (sent["project"], sent["id"]) == ("maintainer/maity", f"evt-{message['seq']}")
    assert sent["body"] == "Hello from the colleague" and sent["at"]
    # The owner's card is the thing the message belongs to: its title, never its body.
    assert sent["task"] == {"id": theirs["id"], "title": "Owner's card"}
    [created_card] = body["cards_created"]
    assert created_card["id"] == mine["id"] and created_card["project"] == "maintainer/maity"
    assert created_card["as_created"]["title"] == "Colleague's card"
    assert created_card["as_created"]["body"] == "Colleague's body"
    [noted] = body["card_notes"]
    assert (noted["id"], noted["body"]) == (written["id"], "A note by the colleague")
    assert noted["card"] == {"id": theirs["id"], "title": "Owner's card"}
    [request] = body["requests_asked"]
    assert (request["id"], request["title"], request["status"]) == (
        asked["id"],
        "Ship it?",
        "answered",
    )
    assert body["answers_given"] == []
    # Nothing that is only the owner's.
    for text in ("Owner's secret plan", "The owner's own words", "Yes, the owner says ship"):
        assert text not in response.text

    # The owner's export has the answer, under the colleague's title.
    [given] = export(owner).json()["answers_given"]
    assert given["request"] == {"id": asked["id"], "title": "Ship it?"}
    assert given["text"] == "Yes, the owner says ship" and given["answered_at"]


def test_redacted_stays_redacted(owner: flow.Human, colleague: flow.Human) -> None:
    theirs = card(owner, "Owner's card")
    message = say(colleague, "Something I regret")
    written = note(colleague, theirs["id"], "A regretted note")
    redacted = owner.post(
        f"{PROJECT}/events/{message['seq']}/redact", {"reason": "the owner's reason"}
    )
    assert redacted.status_code == 200, redacted.text
    path = f"{PROJECT}/tasks/{theirs['id']}/notes/{written['id']}/redact"
    assert owner.post(path, {"reason": "the owner's reason"}).status_code == 200

    response = export(colleague)
    body = response.json()
    [sent] = body["messages"]
    assert sent["redacted"] is True and "body" not in sent
    assert sent["redaction"]["by"] == owner.id
    [noted] = body["card_notes"]
    assert noted["redacted"] is True and "body" not in noted
    for text in ("Something I regret", "A regretted note", "the owner's reason"):
        assert text not in response.text


def test_a_project_they_left(owner: flow.Human, colleague: flow.Human) -> None:
    theirs = card(owner, "Owner's card")
    written = note(colleague, theirs["id"], "Written while a member")
    removed = owner.delete(f"{PROJECT}/members/{colleague.id}")
    assert removed.status_code == 200, removed.text

    body = export(colleague).json()
    [membership] = body["memberships"]
    assert membership["project"] == "maintainer/maity" and membership["left_at"]
    [noted] = body["card_notes"]
    assert noted["body"] == "Written while a member" and noted["id"] == written["id"]
    # The card is no longer theirs to read: its id alone.
    assert noted["card"] == {"id": theirs["id"], "title": None}


def test_what_the_hub_built_from_others_words_stays_out(
    owner: flow.Human, colleague: flow.Human, migrated: Engine
) -> None:
    """A jour fixe decision filed in the caller's name and a card a jour fixe adopted
    carry another person's words (§20.6); a withdrawal reason is its withdrawer's."""
    built = created(colleague.post(f"{PROJECT}/requests", {"class": "decision", "title": "JF"}))
    withdrawn = created(
        colleague.post(f"{PROJECT}/requests", {"class": "decision", "title": "Pulled"})
    )
    adopted = card(colleague, "Proposer's title", "Proposer's text")
    with migrated.begin() as conn:
        conn.execute(
            t.request.update()
            .where(t.request.c.id == built["id"])
            .values(jour_fixe={"round_id": "jfr-x", "proposal_id": "p1"})
        )
        conn.execute(
            t.request.update()
            .where(t.request.c.id == withdrawn["id"])
            .values(status="withdrawn", withdrawn_at=clock.now(), withdraw_reason="An admin's word")
        )
        conn.execute(
            t.card.update().where(t.card.c.id == adopted["id"]).values(jour_fixe={"round": "jfr-x"})
        )
    body = export(colleague).json()
    asked = {r["id"]: r for r in body["requests_asked"]}
    assert built["id"] not in asked
    assert (
        asked[withdrawn["id"]]["withdrawn_at"] and asked[withdrawn["id"]]["withdraw_reason"] is None
    )
    [made] = [c for c in body["cards_created"] if c["id"] == adopted["id"]]
    assert made["as_created"] is None


def test_forge_links_are_login_kind_and_created_never_a_token(
    owner: flow.Human, migrated: Engine
) -> None:
    """§2.9: the forge links (§11.4) as login, kind and when made; never a token."""
    now = clock.now()
    with migrated.begin() as conn:
        conn.execute(
            t.forge_link.insert().values(
                id="fgl-own", human_id=owner.id, forge="github", installation_id=4711,
                account_id=1, account_login="maintainer-gh", account_type="User",
                repository_selection="all", status="active", linked_at=now, checked_at=now,
            )
        )  # fmt: skip
        conn.execute(
            t.forge_token.insert().values(
                human_id=owner.id, forge="github", login="maintainer-gh",
                token_sealed=b"very-secret-sealed-bytes", status="active", set_at=now,
                checked_at=now,
            )
        )  # fmt: skip
    response = export(owner)
    links = response.json()["forge_links"]
    assert [(link["kind"], link["login"]) for link in links] == [
        ("app", "maintainer-gh"),
        ("token", "maintainer-gh"),
    ]
    assert all(set(link) == {"kind", "forge", "login", "status", "created"} for link in links)
    assert "very-secret-sealed-bytes" not in response.text and "4711" not in response.text
