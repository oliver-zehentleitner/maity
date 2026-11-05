"""docs/api.md §6.4 "Restricted text" and §6.1 "Restricted access": the set, the three
routes, the order of their checks, the caps and the quota, and the counter-tests that the
text reaches no other read of the card."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import account_deletion, clock, export, restricted
from maity_hub import tables as t
from maity_hub.routes import restricted as routes
from maity_hub.routes import tasks as tasks_routes
from tests import factory, flow
from tests.conftest import ClientFactory

MARKER = "SECRET-MARKER-7f3a"
STATE_KEYS = {"task_id", "version", "updated_by", "updated_at"}
READ_KEYS = STATE_KEYS | {"text", "history"}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _project(engine: Engine) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.project).where(t.project.c.slug == "maity")).one()


def _set(engine: Engine, mode: str | None, members: list[str] | None = None) -> None:
    project = _project(engine)
    settings = dict(project.settings or {})
    if mode is None:
        settings.pop("restricted_access", None)
    else:
        settings["restricted_access"] = {"mode": mode, "members": members or []}
    with engine.begin() as conn:
        conn.execute(
            update(t.project).where(t.project.c.id == project.id).values(settings=settings)
        )


def _card(owner: flow.Human) -> dict[str, Any]:
    response = owner.post("/projects/maintainer/maity/tasks", {"title": "A card"})
    assert response.status_code == 201, response.text
    card: dict[str, Any] = response.json()
    return card


def _path(card_id: str) -> str:
    return f"/api/v1/projects/maintainer/maity/tasks/{card_id}/restricted"


def get(who: Any, card_id: str) -> Any:
    if isinstance(who, flow.Agent):
        return who.client.get(_path(card_id), headers=who.auth)
    return who.client.get(_path(card_id))


def _headers(who: Any, key: str | None) -> dict[str, str]:
    headers = who.auth if isinstance(who, flow.Agent) else {"X-CSRF-Token": who.csrf}
    return headers | ({"Idempotency-Key": key} if key else {})


def put(who: Any, card_id: str, body: Any, key: str | None = None) -> Any:
    return who.client.put(_path(card_id), content=json.dumps(body), headers=_headers(who, key))


def delete(who: Any, card_id: str, base: int | None = None, key: str | None = None) -> Any:
    params = {"base_version": base} if base is not None else None
    return who.client.delete(_path(card_id), params=params, headers=_headers(who, key))


def _write(who: Any, card_id: str, text: str) -> dict[str, Any]:
    current = get(who, card_id).json()["version"]
    response = put(who, card_id, {"text": text, "base_version": current})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def _reason(response: Any) -> str | None:
    reason: str | None = response.json()["error"]["details"].get("reason")
    return reason


# --- access ------------------------------------------------------------------------------------


def test_without_a_setting_nobody_is_in_the_set(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    for response in (
        get(owner, card["id"]),
        put(owner, card["id"], {"text": "x", "base_version": 0}),
        delete(owner, card["id"]),
    ):
        assert response.status_code == 403 and _reason(response) == "restricted"
        assert response.headers["Cache-Control"] == "no-store"


def test_an_outsider_reaches_no_validation_and_learns_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card, empty = _card(owner), _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], MARKER)
    _set(migrated, "nobody_except", [])  # closed: the text stays stored
    with_text = put(owner, card["id"], {"bogus": True})
    without = put(owner, empty["id"], {"bogus": True})
    assert with_text.status_code == without.status_code == 403
    assert with_text.json() == without.json() and MARKER not in with_text.text
    assert get(owner, "tsk-nosuchcard").status_code == 404
    _set(migrated, "nobody_except", [owner.id])
    assert get(owner, card["id"]).json()["text"] == MARKER  # closing deleted nothing


def test_a_human_from_a_session_not_in_good_standing_is_refused(
    owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.human_id == owner.id)
            .values(method="email", confirmed_at=None, second_factor=None)
        )
    # Outside the set first: the set is checked before good standing.
    assert _reason(get(owner, card["id"])) == "restricted"
    _set(migrated, "nobody_except", [owner.id])
    for response in (
        get(owner, card["id"]),
        put(owner, card["id"], {"text": "x", "base_version": 0}),
        delete(owner, card["id"]),
    ):
        assert response.status_code == 403 and _reason(response) == "not_in_good_standing"


def test_a_listed_agent_reads_and_writes_and_its_owner_does_not_through_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    card = _card(owner)
    _set(migrated, "nobody_except", [agent.id])
    assert _write(agent, card["id"], "from the agent")["updated_by"]["kind"] == "agent"
    assert get(agent, card["id"]).json()["text"] == "from the agent"
    assert _reason(get(owner, card["id"])) == "restricted"


def test_a_bridged_call_is_refused_before_the_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """docs/api.md §6.4: Maity-For on the restricted routes is bridge_no_restricted, even
    when the served agent is in the set and already holds a text."""
    project_id = _project(migrated).id
    served = factory.agent(migrated, project_id, owner.id, "coder")
    bridge = factory.agent(migrated, project_id, owner.id, "coder", instance="brg1")
    made = owner.post(
        f"/projects/maintainer/maity/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "local files for the coder"},
    )
    assert made.status_code == 201, made.text
    card = _card(owner)
    _set(migrated, "nobody_except", [served.agent_id])
    # The served agent itself may write; a bridge calling as it may not.
    direct = make_client()
    written = direct.put(
        _path(card["id"]),
        content=json.dumps({"text": MARKER, "base_version": 0}),
        headers={
            "Authorization": f"Bearer {served.value}",
            "Idempotency-Key": "served-write-0000001",
        },
    )
    assert written.status_code == 200, written.text
    n = 0

    def bridged(method: str, **kwargs: Any) -> Any:
        nonlocal n
        n += 1
        headers = {
            "Authorization": f"Bearer {bridge.value}",
            "Maity-For": served.agent_id,
            "Idempotency-Key": f"bridge-restricted-{n:06d}",
        }
        return getattr(make_client(), method)(_path(card["id"]), headers=headers, **kwargs)

    for response in (
        bridged("get"),
        bridged("put", content=json.dumps({"text": "x", "base_version": 1})),
        bridged("delete"),
    ):
        assert response.status_code == 403 and _reason(response) == "bridge_no_restricted"
        assert MARKER not in response.text
        assert response.headers["Cache-Control"] == "no-store"
    # Order of checks: bridge before the set, so a closed set still names the bridge.
    _set(migrated, None)
    closed = bridged("get")
    assert closed.status_code == 403 and _reason(closed) == "bridge_no_restricted"


# --- who is in the set ---------------------------------------------------------------------------


def test_the_set_resolves_per_mode_trust_isolation_and_owner(
    owner: flow.Human, migrated: Engine
) -> None:
    project = _project(migrated)
    me = _membership(migrated, owner.id)
    other = factory.human(migrated, "other")
    other_m = factory.membership(migrated, project.id, role="member", human_id=other)
    guest = factory.human(migrated, "guesty")
    factory.membership(migrated, project.id, role="member", trust="guest", human_id=guest)
    mine = factory.agent(migrated, project.id, owner.id)
    theirs = factory.agent(migrated, project.id, other)
    guests = factory.agent(migrated, project.id, guest)
    outsider = factory.human(migrated, "outsider")
    orphan = factory.agent(migrated, project.id, outsider)  # its owner is no member

    def resolved() -> set[int]:
        with migrated.connect() as conn:
            return restricted.resolve(conn, _project(migrated))

    assert resolved() == set()  # default closed
    _set(migrated, "all_except", [])
    assert resolved() == {me, other_m, mine.membership_id, theirs.membership_id}
    _set(migrated, "all_except", [other, guest, guests.agent_id])
    # Listing a human leaves out its agents too; a guest is out whatever the list says.
    assert resolved() == {me, mine.membership_id}
    _set(migrated, "nobody_except", [other, guest, guests.agent_id, orphan.agent_id])
    assert resolved() == {other_m}  # no guest, no agent of a guest or of a non-member
    _set(migrated, "nobody_except", [theirs.agent_id])
    assert resolved() == {theirs.membership_id}  # its owner needs no listing
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == theirs.membership_id)
            .values(isolated_since=clock.now())
        )
    assert resolved() == set()  # an isolated member is out
    _set(migrated, "all_except", [])
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == me).values(isolated_since=clock.now())
        )
    # Under all_except an agent is in only while its owner is.
    assert resolved() == {other_m}


def _membership(engine: Engine, principal: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                (t.membership.c.human_id == principal) | (t.membership.c.agent_id == principal)
            )
        ).scalar_one()
        return found


# --- reading and writing ---------------------------------------------------------------------


def test_the_shapes_versions_and_history(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    first = get(owner, card["id"])
    assert first.status_code == 200 and first.headers["Cache-Control"] == "no-store"
    assert first.json() == {
        "task_id": card["id"],
        "text": None,
        "version": 0,
        "updated_by": None,
        "updated_at": None,
        "history": [],
    }
    written = put(owner, card["id"], {"text": "line one\r\nline two\tend", "base_version": 0})
    assert written.status_code == 200 and set(written.json()) == STATE_KEYS
    assert written.json()["version"] == 1
    assert written.json()["updated_by"] == {"kind": "human", "id": owner.id, "handle": "maintainer"}
    cleared = delete(owner, card["id"])  # base_version optional
    assert cleared.status_code == 200 and cleared.json()["version"] == 2
    view = get(owner, card["id"]).json()
    assert set(view) == READ_KEYS and view["text"] is None
    assert [(h["version"], h["action"]) for h in view["history"]] == [(2, "cleared"), (1, "set")]
    _write(owner, card["id"], "again")
    assert get(owner, card["id"]).json()["text"] == "again"
    with migrated.connect() as conn:
        stored = conn.execute(select(t.task_restricted_history)).all()
    assert all(not hasattr(row, "text") for row in stored)  # who and when, never the text


def test_line_endings_are_stored_as_line_feeds(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], "a\r\nb\rc\td")
    assert get(owner, card["id"]).json()["text"] == "a\nb\nc\td"


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"text": "", "base_version": 0}, {"text": "empty"}),
        ({"text": " \n\t ", "base_version": 0}, {"text": "empty"}),
        ({"text": "x" * 1001, "base_version": 0}, {"text": "too_long"}),
        ({"text": "bell\u0007", "base_version": 0}, {"text": "control_character"}),
        ({"text": "zero\u200bwidth", "base_version": 0}, {"text": "control_character"}),
        ({"text": "private\ue000", "base_version": 0}, {"text": "control_character"}),
        ({"text": "line\u2028sep", "base_version": 0}, {"text": "control_character"}),
        ({"text": "para\u2029sep", "base_version": 0}, {"text": "control_character"}),
        ({"text": "fine"}, {"base_version": "required"}),
        ({"base_version": 0}, {"text": "required"}),
        ({"text": "fine", "base_version": 0, "extra": 1}, {"extra": "extra_forbidden"}),
    ],
)
def test_the_body_is_refused_never_trimmed(
    owner: flow.Human, migrated: Engine, body: dict[str, Any], fields: dict[str, str]
) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    response = put(owner, card["id"], body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields
    assert get(owner, card["id"]).json()["version"] == 0


def test_a_lone_surrogate_is_a_control_character(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    raw = '{"text": "half \\ud800 a pair", "base_version": 0}'
    response = owner.client.put(
        _path(card["id"]), content=raw, headers={"X-CSRF-Token": owner.csrf}
    )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"text": "control_character"}


def test_a_thousand_code_points_is_the_limit(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], "ä" * 1000)
    assert len(get(owner, card["id"]).json()["text"]) == 1000


def test_a_stale_version_is_a_conflict_and_a_no_op_is_not(
    owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], MARKER)
    stale = put(owner, card["id"], {"text": "other", "base_version": 0})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "conflict"
    assert stale.json()["error"]["details"] == {"current_version": 1, "base_version": 0}
    assert MARKER not in stale.text
    same = put(owner, card["id"], {"text": MARKER, "base_version": 99})  # changes nothing
    assert same.status_code == 200 and same.json()["version"] == 1
    assert delete(owner, card["id"], base=0).status_code == 409
    assert delete(owner, card["id"], base=1).json()["version"] == 2
    nothing = delete(owner, card["id"], base=99)  # no text: nothing to clear
    assert nothing.status_code == 200 and nothing.json()["version"] == 2


def test_an_archived_project_refuses_a_put_but_not_a_read_or_a_delete(
    owner: flow.Human, migrated: Engine
) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], "keep")
    with migrated.begin() as conn:
        conn.execute(update(t.project).where(t.project.c.slug == "maity").values(state="archived"))
    refused = put(owner, card["id"], {"text": "new", "base_version": 1})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "project_closed"
    assert get(owner, card["id"]).json()["text"] == "keep"
    assert delete(owner, card["id"]).status_code == 200


def test_the_card_cap_counts_puts_and_never_a_delete(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    for n in range(routes.CARD_CAP):
        _write(owner, card["id"], f"text {n}")
    # A write that changes nothing is never rate_limited.
    assert put(owner, card["id"], {"text": "text 9", "base_version": 10}).status_code == 200
    limited = put(owner, card["id"], {"text": "one more", "base_version": 10})
    assert limited.status_code == 429 and int(limited.headers["Retry-After"]) > 0
    assert delete(owner, card["id"]).status_code == 200  # a clearing is not held back


def test_the_membership_cap_counts_puts_and_deletes(owner: flow.Human, migrated: Engine) -> None:
    cards = [_card(owner)["id"] for _ in range(3)]
    _set(migrated, "nobody_except", [owner.id])
    writes = 0
    for card_id in cards:
        for n in range(4):
            _write(owner, card_id, f"text {n}")
            writes += 1
        assert delete(owner, card_id).status_code == 200
        writes += 1
    while writes < routes.MEMBERSHIP_CAP:
        _write(owner, cards[writes % 3], f"more {writes}")
        writes += 1
    current = get(owner, cards[0]).json()
    limited = put(owner, cards[0], {"text": "over", "base_version": current["version"]})
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_the_quota_counts_cards_with_a_text(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes, "QUOTA", 2)
    cards = [_card(owner)["id"] for _ in range(3)]
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, cards[0], "one")
    _write(owner, cards[1], "two")
    _write(owner, cards[1], "two, changed")  # a card that has one keeps changing it
    over = put(owner, cards[2], {"text": "three", "base_version": 0})
    assert over.status_code == 409 and over.json()["error"]["code"] == "restricted_quota"
    assert over.json()["error"]["details"] == {"max": 2}
    assert delete(owner, cards[0]).status_code == 200  # a DELETE frees its place
    assert put(owner, cards[2], {"text": "three", "base_version": 0}).status_code == 200


def test_a_repeat_answers_only_after_the_access_check(owner: flow.Human, migrated: Engine) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    key = "restricted-key-0000001"
    first = put(owner, card["id"], {"text": MARKER, "base_version": 0}, key=key)
    again = put(owner, card["id"], {"text": MARKER, "base_version": 0}, key=key)
    assert first.status_code == again.status_code == 200
    assert again.headers.get("Idempotent-Replayed") == "true" and MARKER not in again.text
    _set(migrated, "nobody_except", [])
    gone = put(owner, card["id"], {"text": MARKER, "base_version": 0}, key=key)
    assert gone.status_code == 403 and _reason(gone) == "restricted"


def test_a_set_change_before_the_project_lock_stops_the_write(
    owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The set closes between the access check ahead of the run and the project lock: the
    write admits again under the lock and refuses (review of #1401)."""
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], MARKER)
    project = _project(migrated)
    closed = dict(project.settings or {}) | {
        "restricted_access": {"mode": "nobody_except", "members": []}
    }
    real = tasks_routes._locked

    def closing_first(conn: Any, mine: Any) -> Any:
        conn.execute(update(t.project).where(t.project.c.id == project.id).values(settings=closed))
        return real(conn, mine)

    monkeypatch.setattr(routes, "_locked", closing_first)
    written = put(owner, card["id"], {"text": "after", "base_version": 1})
    cleared = delete(owner, card["id"], base=1)
    for response in (written, cleared):
        assert response.status_code == 403 and _reason(response) == "restricted"
    monkeypatch.setattr(routes, "_locked", real)
    after = get(owner, card["id"]).json()
    assert after["text"] == MARKER and after["version"] == 1


@pytest.mark.parametrize(
    "given",
    ["\u00b2", "\u0661", "1\u00b2", "9" * 5000, "-1", " 1", "1.0"],
    ids=["superscript", "arabic_indic", "mixed", "overlong", "negative", "space", "decimal"],
)
def test_a_base_version_that_is_not_ascii_digits_is_invalid(
    owner: flow.Human, migrated: Engine, given: str
) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    _write(owner, card["id"], MARKER)
    response = owner.client.delete(
        _path(card["id"]), params={"base_version": given}, headers=_headers(owner, None)
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"] == {"fields": {"base_version": "int_parsing"}}
    assert get(owner, card["id"]).json()["text"] == MARKER


# --- never a card field --------------------------------------------------------------------------


def test_the_text_reaches_no_other_read_of_the_card(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = _card(owner)
    _set(migrated, "nobody_except", [owner.id])
    with migrated.connect() as conn:
        events_before = conn.execute(select(t.event.c.seq)).all()
    _write(owner, card["id"], MARKER)
    after = owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()
    assert MARKER not in json.dumps(after) and "restricted" not in after
    assert after["updated_at"] == card["updated_at"] and after["rank"] == card["rank"]
    for path in (
        "/projects/maintainer/maity/tasks",
        f"/projects/maintainer/maity/tasks?q={MARKER}",
        f"/projects/maintainer/maity/tasks/{card['id']}/history",
        "/projects/maintainer/maity/overview",
    ):
        response = owner.get(path)
        assert response.status_code == 200, (path, response.text)
        assert MARKER not in response.text, path
    assert owner.get(f"/projects/maintainer/maity/tasks?q={MARKER}").json()["items"] == []
    with migrated.connect() as conn:
        events_after = conn.execute(select(t.event)).all()
    assert len(events_after) == len(events_before)  # no task_updated, no event at all yet
    assert all(MARKER not in json.dumps(row.payload) for row in events_after)
    agent = flow.agent(make_client, owner)
    assert MARKER not in agent.resume().text


@pytest.mark.parametrize("verb", ["post", "patch"])
def test_a_card_body_naming_restricted_is_invalid(
    owner: flow.Human, migrated: Engine, verb: str
) -> None:
    card = _card(owner)
    if verb == "post":
        response = owner.post("/projects/maintainer/maity/tasks", {"title": "x", "restricted": "y"})
    else:
        response = owner.patch(
            f"/projects/maintainer/maity/tasks/{card['id']}", {"restricted": "y"}
        )
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"]["restricted"] == "extra_forbidden"


# --- export and deletion -------------------------------------------------------------------------


def test_the_export_carries_only_own_texts_of_a_set_the_caller_is_in(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    mine, theirs = _card(owner), _card(owner)
    _set(migrated, "nobody_except", [owner.id, agent.id])
    _write(owner, mine["id"], MARKER)
    _write(agent, theirs["id"], "the agent's")
    exported = owner.get("/me/export")
    assert exported.status_code == 200, exported.text
    texts = exported.json()["restricted_texts"]
    assert [(x["card_id"], x["version"], x["text"]) for x in texts] == [(mine["id"], 1, MARKER)]
    assert texts[0]["project"] == "maintainer/maity" and texts[0]["updated_at"]
    assert "the agent's" not in exported.text
    _set(migrated, "nobody_except", [agent.id])  # out of the set: nothing to export
    with migrated.connect() as conn:
        assert export.build(conn, owner.id, clock.now())["restricted_texts"] == []


def test_a_deleted_account_leaves_the_private_lists(owner: flow.Human, migrated: Engine) -> None:
    project = _project(migrated)
    me = _membership(migrated, owner.id)
    other = factory.human(migrated, "other")
    other_m = factory.membership(migrated, project.id, role="member", human_id=other)
    _card(owner)  # an event to stand for a restricted-text one: PR B writes those
    with migrated.begin() as conn:
        seq = conn.execute(select(t.event.c.seq).order_by(t.event.c.seq.desc())).scalars().first()
        conn.execute(
            insert(t.restricted_event_list),
            [{"seq": seq, "membership_id": me}, {"seq": seq, "membership_id": other_m}],
        )
        account_deletion._off_restricted_lists(conn, other, [])
        left = conn.execute(select(t.restricted_event_list.c.membership_id)).scalars().all()
    assert left == [me]
