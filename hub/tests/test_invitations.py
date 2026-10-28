"""docs/api.md §3.4: invitations for humans — issue, list, revoke, the page, accepting —
and registration admitted by an address-bound invitation (§2.7.1)."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, invitation_mail, invitations, registration, registration_mail
from maity_hub import tables as t
from maity_hub.middleware import _logged_path
from maity_hub.routes import joins
from maity_hub.routes import registration as registration_routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_join_host import join_client
from tests.test_registration import MAIL, PASSWORD, SIGNING, hub, pending

PATH = "/projects/maintainer/maity/invitations"


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    for limiter in (
        joins.EXCHANGE_BY_ADDRESS,
        invitations.PER_PROJECT,
        registration_routes.BY_SOURCE,
        registration_routes.BY_PAIR_SHORT,
        registration_routes.BY_PAIR_DAY,
        registration_routes.BY_ADDRESS_DAY,
    ):
        limiter._hits.clear()
    registration.BREAKER._at.clear()
    registration.BREAKER._open_until = 0.0
    yield


@pytest.fixture
def mailed(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """What would be mailed: invitation links, and registration mails by kind."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        invitation_mail, "send", lambda conn, *, invitation_id, to, url: sent.append(("invite", to))
    )
    monkeypatch.setattr(
        registration_mail,
        "send",
        lambda conn, *, kind, to, pending_id=None, **_: sent.append((kind, to)),
    )
    return sent


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(select(t.project.c.id)).scalar_one())


def member(
    make_client: ClientFactory, engine: Engine, handle: str, role: str = "member"
) -> flow.Human:
    """A human who is a member of `maity` with `role`."""
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), role, human_id=human.id)
    return human


def issue(by: flow.Human, **body: Any) -> dict[str, Any]:
    created = by.post(PATH, body)
    assert created.status_code == 201, created.text
    found: dict[str, Any] = created.json()
    return found


def token_of(invitation: dict[str, Any]) -> str:
    return str(invitation["url"].rsplit("/", 1)[1])


def page(client: Any, token: str) -> Any:
    return client.get(f"/api/v1/invitations/{token}")


def accept(human: flow.Human, token: str) -> Any:
    return human.post(f"/invitations/{token}/accept")


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def kinds(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event).where(t.event.c.kind.in_(invitations.KINDS)).order_by(t.event.c.seq)
            )
        )


# --- issue, list, revoke ----------------------------------------------------------------


def test_an_owner_issues_one_and_its_url_is_shown_once(
    owner: flow.Human, migrated: Engine, mailed: list[tuple[str, str]]
) -> None:
    made = issue(owner, address="Anna@Example.org", note="You review the web side.")
    assert made["id"].startswith("inv-") and (made["trust"], made["role"]) == ("member", "coder")
    assert made["url"].startswith("https://hub.example/#/invite/")
    assert len(token_of(made)) == 22
    expires = datetime.fromisoformat(made["expires_at"]) - datetime.fromisoformat(
        made["created_at"]
    )
    assert expires == timedelta(days=1)
    assert mailed == [("invite", "Anna@Example.org")]
    listed = owner.get(PATH).json()
    assert [i["id"] for i in listed["items"]] == [made["id"]]
    assert "url" not in listed["items"][0] and token_of(made) not in str(listed)
    with migrated.connect() as conn:
        row = conn.execute(select(t.invitation)).one()
    assert row.token_hash != token_of(made) and row.address_normalized == "anna@example.org"
    [created] = kinds(migrated)
    assert created.payload == {
        "id": made["id"],
        "trust": "member",
        "role": "coder",
        "address_bound": True,
    }
    assert created.audience == [f"member:{owner.id}"]


def test_what_issuing_refuses(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    assert owner.post(PATH, {"ttl_seconds": 604_801}).json()["error"]["details"]["fields"] == {
        "ttl_seconds": "out_of_range"
    }
    assert owner.post(PATH, {"ttl_seconds": 59}).status_code == 400
    assert owner.post(PATH, {"note": "x" * 1025}).status_code == 400
    assert owner.post(PATH, {"note": "é" * 513}).status_code == 400  # 1 KiB of UTF-8
    assert owner.post(PATH, {"address": "not an address"}).status_code == 400
    assert owner.post(PATH, {"role": "boss"}).status_code == 400
    admin = member(make_client, migrated, "an-admin", "admin")
    assert issue(admin, role="reviewer")["role"] == "reviewer"
    assert owner.post(PATH, {"role": "member"}).status_code == 400  # the old single role
    for body in ({"trust": "admin"}, {"trust": "owner"}, {"trust": "admin", "role": "proxy"}):
        refused = admin.post(PATH, body)
        assert (refused.status_code, reason(refused)) == (403, "owner_only")
    assert issue(owner, trust="owner")["trust"] == "owner"
    plain = member(make_client, migrated, "a-member")
    assert plain.post(PATH, {}).status_code == 403
    assert plain.get(PATH).status_code == 403


def test_an_agent_never_touches_invitations(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    lead = flow.agent(make_client, owner, role="admin")
    made = issue(owner)
    assert lead.post(PATH, {}).status_code == 403
    assert lead.get(PATH).status_code == 403
    revoked = lead.client.delete(f"/api/v1{PATH}/{made['id']}", headers=lead.auth | lead.key())
    assert revoked.status_code == 403
    # An admin agent reads every event of the project, but not these (§3.4, §8.2).
    seen = lead.get("/projects/maintainer/maity/events?after=0").json()["items"]
    assert not [e for e in seen if e["kind"] in invitations.KINDS]


def test_twenty_an_hour_per_project(owner: flow.Human) -> None:
    for _ in range(20):
        issue(owner)
    assert owner.post(PATH, {}).status_code == 429


def test_revoking_and_what_cannot_be_revoked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    made = issue(owner)
    first = owner.delete(f"{PATH}/{made['id']}")
    assert first.status_code == 200 and first.json()["revoked_at"]
    again = owner.delete(f"{PATH}/{made['id']}")
    assert again.status_code == 200 and again.json() == first.json()
    assert page(make_client(), token_of(made)).status_code == 404
    revoked_guest = flow.human(make_client, migrated, "late")
    assert accept(revoked_guest, token_of(made)).status_code == 404
    expired = issue(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.invitation)
            .where(t.invitation.c.id == expired["id"])
            .values(expires_at=clock.now() - timedelta(seconds=1))
        )
    too_late = owner.delete(f"{PATH}/{expired['id']}")
    assert too_late.json()["error"]["details"] == {"from": "expired", "to": "revoked"}
    used = issue(owner)
    guest = flow.human(make_client, migrated, "guest")
    assert accept(guest, token_of(used)).status_code == 201
    refused = owner.delete(f"{PATH}/{used['id']}")
    assert refused.status_code == 409
    assert refused.json()["error"]["details"] == {"from": "used", "to": "revoked"}
    assert owner.delete(f"{PATH}/inv-unknown").status_code == 404
    assert [e.kind for e in kinds(migrated)] == [
        "invitation_created",
        "invitation_revoked",
        "invitation_created",
        "invitation_created",
        "invitation_used",
    ]  # the second DELETE told nobody again


def test_the_list_keeps_each_ended_one_thirty_days_from_its_end(
    owner: flow.Human, migrated: Engine
) -> None:
    """§3.4: open ones, and used, revoked, voided or expired ones by the time they ended."""
    made = {name: issue(owner) for name in ("open", "old_revoked", "revoked", "voided",
                                            "expired", "old_expired")}  # fmt: skip
    now = clock.now()
    long_ago, lately = now - timedelta(days=31), now - timedelta(days=2)
    changes: dict[str, dict[str, Any]] = {
        "old_revoked": {"revoked_at": long_ago, "expires_at": now - timedelta(days=29)},
        "revoked": {"revoked_at": lately},
        "voided": {"voided_at": lately, "void_reason": "issuer"},
        "expired": {"expires_at": lately},
        "old_expired": {"expires_at": long_ago},
    }
    with migrated.begin() as conn:
        for name, values in changes.items():
            conn.execute(
                update(t.invitation).where(t.invitation.c.id == made[name]["id"]).values(**values)
            )
    listed = {i["id"] for i in owner.get(PATH).json()["items"]}
    assert listed == {made[n]["id"] for n in ("open", "revoked", "voided", "expired")}
    first = owner.get(f"{PATH}?limit=3").json()
    rest = owner.get(f"{PATH}?limit=3&cursor={first['next_cursor']}").json()
    assert len(first["items"]) == 3 and rest["next_cursor"] is None
    assert {i["id"] for i in first["items"] + rest["items"]} == listed


# --- the page ---------------------------------------------------------------------------


def test_the_page_says_who_invites_to_what(owner: flow.Human, make_client: ClientFactory) -> None:
    made = issue(owner, role="reviewer", note="Welcome.")
    shown = page(make_client(), token_of(made))
    assert shown.status_code == 200
    assert shown.json() == {
        "project": {
            "slug": "maity",
            "full_name": "maintainer/maity",
            "name": "Maity",
            "logo_url": None,
        },
        "trust": "member",
        "role": "reviewer",
        "invited_by": {"display_name": shown.json()["invited_by"]["display_name"]},
        "note": "Welcome.",
        "expires_at": made["expires_at"],
        "address_bound": False,
        "registration": "sign_in_only",  # a fresh instance is closed and has no mail
    }
    assert "handle" not in str(shown.json()) and token_of(made) not in shown.text


def test_the_page_is_one_not_found_for_every_dead_token(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    visitor = make_client()
    expired = issue(owner, ttl_seconds=60)
    with migrated.begin() as conn:
        conn.execute(
            update(t.invitation)
            .where(t.invitation.c.id == expired["id"])
            .values(expires_at=clock.now() - timedelta(seconds=1))
        )
    answers = [page(visitor, "A" * 22), page(visitor, token_of(expired))]
    assert {a.status_code for a in answers} == {404}
    assert answers[0].json() == answers[1].json()


@pytest.mark.parametrize(
    ("env", "bound", "expected"),
    [
        ({"MAITY_REGISTRATION": "open"}, False, "sign_in_or_register"),
        ({}, True, "sign_in_or_register"),  # closed, with mail: an address-bound one admits
        ({}, False, "sign_in_only"),  # an unbound one admits nobody to register
        ({"MAITY_REGISTRATION": "allowlist", "MAITY_REGISTRATION_DOMAINS": "@x.org"}, True,
         "sign_in_or_register"),
    ],
)  # fmt: skip
def test_registration_on_the_page_follows_the_instance_and_the_invitation(
    owner: flow.Human,
    make_client: ClientFactory,
    env: dict[str, str],
    bound: bool,
    expected: str,
) -> None:
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL, **env)
    visitor = make_client(mail=settings.mail, registration=settings.registration)
    made = issue(owner, **({"address": "anna@example.org"} if bound else {}))
    assert page(visitor, token_of(made)).json()["registration"] == expected


def test_no_mail_no_registration_on_the_page(owner: flow.Human, make_client: ClientFactory) -> None:
    settings = hub(MAITY_REGISTRATION="open")
    visitor = make_client(mail=settings.mail, registration=settings.registration)
    made = issue(owner, address="anna@example.org")
    assert page(visitor, token_of(made)).json()["registration"] == "sign_in_only"


def test_the_page_and_accept_share_the_join_exchange_limit(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    visitor = make_client(peer="198.51.100.20")
    made = issue(owner)
    answers = [page(visitor, token_of(made)).status_code for _ in range(11)]
    assert answers == [200] * 10 + [429]


def test_the_join_host_never_serves_the_page(owner: flow.Human, make_client: ClientFactory) -> None:
    made = issue(owner)
    answer = join_client(make_client).get(
        f"/api/v1/invitations/{token_of(made)}", follow_redirects=False
    )
    assert answer.status_code in (302, 404) and "invited_by" not in answer.text


def test_the_token_is_masked_in_the_log() -> None:
    assert _logged_path({"path": "/api/v1/invitations/9fK2abc/accept"}) == (
        "/api/v1/invitations/…/accept"
    )


# --- accepting --------------------------------------------------------------------------


def test_accepting_makes_a_member_and_uses_the_invitation(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    made = issue(owner, role="reviewer")
    guest = flow.human(make_client, migrated, "guest")
    joined = accept(guest, token_of(made))
    assert joined.status_code == 201, joined.text
    shown = joined.json()
    assert (shown["id"], shown["trust"], shown["role"], shown["kind"]) == (
        guest.id,
        "member",
        "reviewer",
        "human",
    )
    assert guest.get("/projects/maintainer/maity").status_code == 200
    owners_view = owner.get(f"/projects/maintainer/maity/members/{owner.id}").json()
    guests_view = owner.get(f"/projects/maintainer/maity/members/{guest.id}").json()
    for key in ("briefing", "briefing_version", "briefing_by"):  # as every human starts
        assert guests_view.get(key) == owners_view.get(key), key
    used = owner.get(PATH).json()["items"][0]
    assert used["used_by"] == guest.id and used["used_at"]
    with migrated.connect() as conn:
        joined_event = conn.execute(
            select(t.event).where(t.event.c.kind == "member_joined").order_by(t.event.c.seq.desc())
        ).first()
    assert joined_event is not None and joined_event.payload["id"] == guest.id
    assert [e.kind for e in kinds(migrated)] == ["invitation_created", "invitation_used"]
    assert accept(guest, token_of(made)).status_code == 404  # used: as if it never was


def test_accepting_needs_a_session(owner: flow.Human, make_client: ClientFactory) -> None:
    made = issue(owner)
    assert make_client().post(f"/api/v1/invitations/{token_of(made)}/accept").status_code == 401


def test_a_closed_project_and_a_pending_account_accept_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    made = issue(owner)
    guest = flow.human(make_client, migrated, "guest")
    with migrated.begin() as conn:
        conn.execute(
            update(t.human).where(t.human.c.id == guest.id).values(account_status="pending")
        )
    waiting = accept(guest, token_of(made))
    assert (waiting.status_code, reason(waiting)) == (403, "account_pending")
    unknown = accept(guest, "A" * 22)  # the same: a pending account learns nothing
    assert (unknown.status_code, reason(unknown)) == (403, "account_pending")
    with migrated.begin() as conn:
        conn.execute(
            update(t.human).where(t.human.c.id == guest.id).values(account_status="active")
        )
        conn.execute(update(t.project).values(state="archived"))
    closed = accept(guest, token_of(made))
    assert (closed.status_code, closed.json()["error"]["code"]) == (409, "project_closed")
    assert owner.get(PATH).json()["items"][0]["used_at"] is None  # it waits


def test_an_address_bound_invitation_is_for_that_address(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = issue(owner, address="anna@example.org")
    guest = flow.human(make_client, migrated, "guest")
    mismatch = accept(guest, token_of(made))
    assert (mismatch.status_code, reason(mismatch)) == (403, "invitation_address_mismatch")
    monkeypatch.setattr(invitations, "account_address", lambda conn, human_id: "anna@example.org")
    assert accept(guest, token_of(made)).status_code == 201


def test_a_member_already_and_two_invitations_for_one_person(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first, second = issue(owner), issue(owner)
    guest = flow.human(make_client, migrated, "guest")
    assert accept(guest, token_of(first)).status_code == 201
    again = accept(guest, token_of(second))
    assert again.status_code == 400
    assert again.json()["error"]["details"]["fields"] == {"token": "already_member"}
    assert owner.get(PATH).json()["items"][0]["used_at"] is None  # open for someone else
    assert accept(owner, token_of(second)).status_code == 400  # the owner is one too


def test_an_address_bound_invitation_of_a_member_is_used_up(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = member(make_client, migrated, "guest")
    made = issue(owner, address="guest@example.org")
    monkeypatch.setattr(invitations, "account_address", lambda conn, human_id: "guest@example.org")
    assert accept(guest, token_of(made)).status_code == 400
    assert owner.get(PATH).json()["items"][0]["used_by"] == guest.id


def test_an_issuer_who_lost_the_authority_voids_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    admin = member(make_client, migrated, "an-admin", "admin")
    made = issue(admin)
    with migrated.begin() as conn:  # demoted between issue and accept
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(trust="member")
        )
    guest = flow.human(make_client, migrated, "guest")
    void = accept(guest, token_of(made))
    assert (void.status_code, reason(void)) == (403, "invitation_void")
    listed = owner.get(PATH).json()["items"][0]
    assert listed["voided_at"] and listed["used_at"] is None
    voided = kinds(migrated)[-1]
    assert voided.kind == "invitation_voided" and f"member:{admin.id}" in voided.audience
    assert voided.payload == {
        "id": made["id"],
        "trust": "member",
        "role": "coder",
        "address_bound": False,
    }
    assert accept(guest, token_of(made)).status_code == 404


def test_an_owner_invitation_needs_the_issuer_still_owner(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    second = member(make_client, migrated, "co-owner", "owner")
    made = issue(second, trust="admin")
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == second.id).values(trust="admin")
        )
    guest = flow.human(make_client, migrated, "guest")
    assert reason(accept(guest, token_of(made))) == "invitation_void"


def test_two_accepts_at_once_use_it_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The second waits for the first's project lock and then finds it used. SQLite
    serialises every writer anyway, so this runs on PostgreSQL and MariaDB. The first
    transaction is released on every exit before the worker is joined."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the lock is for the server databases")
    made = issue(owner)
    guest = flow.human(make_client, migrated, "guest")
    first = migrated.connect()
    started, answered = threading.Event(), threading.Event()

    def second() -> int:
        started.set()
        status = int(accept(guest, token_of(made)).status_code)
        answered.set()
        return status

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        events.lock_project(first, project_id(migrated))
        first.execute(
            update(t.invitation)
            .where(t.invitation.c.id == made["id"])
            .values(used_at=clock.now(), used_by=owner.id)
        )
        waiting = pool.submit(second)
        assert started.wait(timeout=10)
        assert not answered.wait(timeout=0.5)  # held by the first
        first_tx.commit()
        assert waiting.result(timeout=10) == 404
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)


def _held(migrated: Engine, change: Any, call: Any) -> Any:
    """`change` (a held transaction under the project's lock) commits while `call`
    waits for that lock; returns `call`'s answer. Released before the worker is joined."""
    first = migrated.connect()
    started, answered = threading.Event(), threading.Event()

    def other() -> Any:
        started.set()
        found = call()
        answered.set()
        return found

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        events.lock_project(first, project_id(migrated))
        change(first)
        waiting = pool.submit(other)
        assert started.wait(timeout=10)
        assert not answered.wait(timeout=0.5)  # held by the first
        first_tx.commit()
        return waiting.result(timeout=10)
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)


def test_an_accept_that_wins_leaves_nothing_to_revoke(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A revocation waits for an accept in flight and then finds it used (§3.4)."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the lock is for the server databases")
    made = issue(owner)

    def use(conn: Any) -> None:
        conn.execute(
            update(t.invitation)
            .where(t.invitation.c.id == made["id"])
            .values(used_at=clock.now(), used_by=owner.id)
        )

    answer = _held(migrated, use, lambda: owner.delete(f"{PATH}/{made['id']}"))
    assert answer.status_code == 409
    assert answer.json()["error"]["details"] == {"from": "used", "to": "revoked"}
    assert [e.kind for e in kinds(migrated)] == ["invitation_created"]


def test_two_revocations_tell_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the lock is for the server databases")
    made = issue(owner)
    path = f"{PATH}/{made['id']}"

    def revoke(conn: Any) -> None:
        conn.execute(
            update(t.invitation)
            .where(t.invitation.c.id == made["id"])
            .values(revoked_at=clock.now())
        )

    answer = _held(migrated, revoke, lambda: owner.delete(path))
    assert answer.status_code == 200 and answer.json()["revoked_at"]
    assert [e.kind for e in kinds(migrated)] == ["invitation_created"]  # the waiter told no one


# --- registration admitted by an invitation (§2.7.1) ------------------------------------


def test_closed_registers_an_invited_address_and_answers_every_address_alike(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    mailed: list[tuple[str, str]],
) -> None:
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)  # closed, with mail
    visitor = make_client(mail=settings.mail, registration=settings.registration)
    made = issue(owner, address="anna@example.org")
    issue(owner)  # an unbound one admits nobody
    mailed.clear()

    def register(given: str) -> Any:
        return visitor.post("/api/v1/auth/register", json={"address": given, "password": PASSWORD})

    answers = [register("Anna@Example.org"), register("bob@example.org")]
    assert [(a.status_code, a.json()) for a in answers] == [(202, {"expires_in": 86400})] * 2
    assert [row.address_normalized for row in pending(migrated)] == ["anna@example.org"]
    assert mailed == [("register_link", "Anna@Example.org")]
    owner.delete(f"{PATH}/{made['id']}")  # it stops admitting
    mailed.clear()
    assert register("anna@example.org").status_code == 202
    assert mailed == []


def test_an_invitation_whose_issuer_lost_authority_admits_nobody_to_register(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    mailed: list[tuple[str, str]],
) -> None:
    settings = hub(MAITY_MAIL_SIGNING_KEY=SIGNING, **MAIL)
    visitor = make_client(mail=settings.mail, registration=settings.registration)
    admin = member(make_client, migrated, "an-admin", "admin")
    issue(admin, address="anna@example.org")
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(active=None)
        )
    mailed.clear()
    answer = visitor.post(
        "/api/v1/auth/register", json={"address": "anna@example.org", "password": PASSWORD}
    )
    assert answer.status_code == 202 and mailed == [] and pending(migrated) == []
