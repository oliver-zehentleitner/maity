"""docs/api.md §6.29: a human's contacts. `PUT` and `DELETE /people/{handle}/contact`, `GET
/me/contacts` and `GET /me/contact-of`, the field `contact` of `GET /people/{handle}`, the
export and the account deletion."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import Engine, delete, func, select, update

from maity_hub import account_deletion, clock, contacts, write_guard
from maity_hub import tables as t
from maity_hub.errors import ApiError
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import make_org


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "anna")


@pytest.fixture
def ben(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "ben")


@pytest.fixture(autouse=True)
def _fresh_limit() -> None:
    contacts.ADDED.configure(contacts.PER_DAY, contacts.DAY)


def put(who: flow.Human, handle: str) -> Any:
    return who.client.put(f"/api/v1/people/{handle}/contact", headers={"X-CSRF-Token": who.csrf})


def remove(who: flow.Human, handle: str) -> Any:
    return who.delete(f"/people/{handle}/contact")


def listed(who: flow.Human, side: str, **query: Any) -> list[str]:
    got = who.get(f"/me/{side}", params=query)
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "private, no-store"
    return [item["handle"] for item in got.json()["items"]]


def _reason(response: Any) -> str:
    assert response.status_code == 400, response.text
    reason: str = response.json()["error"]["details"]["reason"]
    return reason


def _rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(t.contact)).scalar_one())


def _set_human(engine: Engine, human_id: str, **values: Any) -> None:
    with engine.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == human_id).values(**values))


def test_adding_goes_one_way_and_each_side_sees_its_own_list(
    anna: flow.Human, ben: flow.Human
) -> None:
    assert put(anna, "ben").status_code == 204
    assert put(anna, "ben").status_code == 204  # again: nothing changes
    assert listed(anna, "contacts") == ["ben"]  # ben may contact anna
    assert listed(anna, "contact-of") == []
    assert listed(ben, "contacts") == []
    assert listed(ben, "contact-of") == ["anna"]  # whom ben may contact
    item = ben.get("/me/contact-of").json()["items"][0]
    assert set(item) == {"handle", "display_name", "avatar_url", "since"}
    assert remove(anna, "ben").status_code == 204
    assert remove(anna, "ben").status_code == 204  # again: nothing to remove
    assert listed(anna, "contacts") == [] and listed(ben, "contact-of") == []


def test_the_people_page_says_only_whether_the_person_is_a_contact(
    ben: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)  # maintainer
    project = flow.project(owner)
    factory.membership(migrated, project["id"], "coder", human_id=ben.id)  # shown to ben
    put(ben, "maintainer")
    assert ben.get("/people/maintainer").json()["contact"] is True
    assert "contact" not in ben.get("/people/ben").json()  # the caller's own
    remove(ben, "maintainer")
    assert ben.get("/people/maintainer").json()["contact"] is False


def test_the_people_page_has_no_contact_field_for_an_organisation(anna: flow.Human) -> None:
    make_org(anna, "acme", "Acme")
    assert "contact" not in anna.get("/people/acme").json()


def test_who_may_add_whom(anna: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)  # maintainer
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    refused = agent.client.put(
        "/api/v1/people/anna/contact", headers={"Authorization": f"Bearer {agent.credential}"}
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    assert make_client().put("/api/v1/people/anna/contact").status_code in (401, 403)
    assert agent.get("/me/contacts").status_code == 403
    assert _reason(put(anna, "anna")) == "self"
    make_org(anna, "acme", "Acme")
    assert _reason(put(anna, "acme")) == "not_a_person"
    with migrated.begin() as conn:
        conn.execute(update(t.org).where(t.org.c.handle == "acme").values(deleted_at=clock.now()))
    assert put(anna, "acme").status_code == 404  # as GET /people answers a deleted one
    assert put(anna, "nobody-here").status_code == 404
    agent_handle = owner.get(f"/projects/maintainer/maity/members/{agent.id}").json()["handle"]
    assert put(anna, agent_handle).status_code == 404  # an agent's handle names nobody here
    assert _rows(migrated) == 0


def test_a_stranger_can_be_added_by_handle_or_alias(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    # Handles are public: no shared project and no page needed (§6.29).
    assert ben.get("/people/anna").status_code == 404  # anna shows ben nothing
    assert put(ben, "anna").status_code == 204
    assert anna.patch("/me", {"handle": "anna-two"}).status_code == 200
    assert listed(ben, "contacts") == ["anna-two"]  # the current handle
    assert remove(ben, "anna").status_code == 204  # the alias still names her
    assert listed(ben, "contacts") == []


@pytest.mark.parametrize(
    ("column", "value"),
    [("suspended_at", "now"), ("account_status", "pending"), ("deleted_at", "now")],
)
def test_an_account_that_is_not_active_cannot_be_added(
    anna: flow.Human, ben: flow.Human, migrated: Engine, column: str, value: str
) -> None:
    _set_human(migrated, ben.id, **{column: clock.now() if value == "now" else value})
    assert put(anna, "ben").status_code == 404
    assert _rows(migrated) == 0


def test_a_suspended_contact_is_left_out_of_the_lists_and_can_be_removed(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    put(anna, "ben")
    put(ben, "anna")
    _set_human(migrated, ben.id, suspended_at=clock.now())
    assert listed(anna, "contacts") == [] and listed(anna, "contact-of") == []
    _set_human(migrated, ben.id, suspended_at=None)
    assert listed(anna, "contacts") == ["ben"]  # the row stayed
    _set_human(migrated, ben.id, suspended_at=clock.now())
    assert remove(anna, "ben").status_code == 204  # can always be removed
    assert remove(anna, "nobody-here").status_code == 404
    _set_human(migrated, ben.id, suspended_at=None)
    assert listed(anna, "contacts") == []


def test_the_lists_are_paged_newest_first(
    anna: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    for n in range(5):
        flow.human(make_client, migrated, f"p{n}")
        assert put(anna, f"p{n}").status_code == 204
    first = anna.get("/me/contacts", params={"limit": 2}).json()
    assert [i["handle"] for i in first["items"]] == ["p4", "p3"]
    second = anna.get("/me/contacts", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert [i["handle"] for i in second["items"]] == ["p2", "p1"]
    last = anna.get("/me/contacts", params={"limit": 2, "cursor": second["next_cursor"]}).json()
    assert [i["handle"] for i in last["items"]] == ["p0"] and last["next_cursor"] is None
    # A cursor of one list does not open the other.
    assert anna.get("/me/contact-of", params={"cursor": first["next_cursor"]}).status_code == 400
    assert anna.get("/me/contacts", params={"limit": 0}).status_code == 400


def test_at_most_a_hundred_new_contacts_a_day(
    anna: flow.Human, ben: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    contacts.ADDED.configure(2, contacts.DAY)
    flow.human(make_client, migrated, "cleo")
    flow.human(make_client, migrated, "dora")
    assert put(anna, "ben").status_code == 204
    assert put(anna, "cleo").status_code == 204
    assert put(anna, "ben").status_code == 204  # already a contact: not counted
    refused = put(anna, "dora")
    assert refused.status_code == 429 and int(refused.headers["Retry-After"]) > 0
    assert remove(anna, "ben").status_code == 204  # removing frees nothing
    assert put(anna, "ben").status_code == 429
    assert listed(anna, "contacts") == ["cleo"]


def test_a_refused_add_spends_no_attempt(anna: flow.Human, ben: flow.Human) -> None:
    contacts.ADDED.configure(1, contacts.DAY)
    assert put(anna, "nobody-here").status_code == 404
    assert _reason(put(anna, "anna")) == "self"
    assert put(anna, "ben").status_code == 204


def test_an_add_that_fails_after_its_count_gives_the_attempt_back(
    anna: flow.Human, ben: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    contacts.ADDED.configure(1, contacts.DAY)

    def fails(conn: Any, human_id: str, contact_id: str) -> bool:
        raise ApiError(409, "conflict", "a failure after the count")

    with monkeypatch.context() as patched:
        patched.setattr(contacts, "add", fails)
        assert put(anna, "ben").status_code == 409
    assert put(anna, "ben").status_code == 204  # the one attempt was given back


def test_an_add_another_call_made_first_gives_the_attempt_back(
    anna: flow.Human,
    ben: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contacts.ADDED.configure(1, contacts.DAY)
    flow.human(make_client, migrated, "cleo")
    with monkeypatch.context() as patched:
        patched.setattr(contacts, "add", lambda conn, human_id, contact_id: False)  # lost race
        assert put(anna, "ben").status_code == 204
    assert put(anna, "cleo").status_code == 204  # the attempt was given back


def test_the_export_carries_each_side_where_it_belongs(
    anna: flow.Human, ben: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.human(make_client, migrated, "cleo")
    put(anna, "ben")  # one way: ben may contact anna
    put(ben, "cleo")
    body = anna.get("/me/export").json()
    assert [c["handle"] for c in body["contacts"]] == ["ben"]
    assert body["contact_of"] == []
    assert set(body["contacts"][0]) == {"handle", "since"}
    body = ben.get("/me/export").json()
    assert [c["handle"] for c in body["contacts"]] == ["cleo"]
    assert [c["handle"] for c in body["contact_of"]] == ["anna"]


def test_deleting_an_account_ends_its_contacts_both_ways(
    anna: flow.Human, ben: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    cleo = flow.human(make_client, migrated, "cleo")
    put(anna, "ben")
    put(ben, "anna")
    put(cleo, "anna")
    with migrated.begin() as conn:
        account_deletion.delete_account(conn, anna.client.app.state.settings, ben.id)  # type: ignore[attr-defined]
    assert _rows(migrated) == 1  # only cleo → anna
    assert listed(anna, "contacts") == [] and listed(anna, "contact-of") == ["cleo"]


# --- a deletion of the person added, at the same moment (#1532 review) ------------------------


def _add(conn: Any, me: str, handle: str) -> bool:
    """The `PUT`'s work in one transaction, as the route does it."""
    return contacts.add(conn, me, contacts.target(conn, me, handle, active=True))


def test_an_add_that_waits_for_the_persons_deletion_is_refused(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    from tests.concurrency import finished, race, waiting

    with race(migrated) as r:
        deletion, adding = r.first, r.second
        account_deletion.lock_account(deletion, ben.id)
        account_deletion.delete_account(deletion, anna.client.app.state.settings, ben.id)  # type: ignore[attr-defined]
        step = r.run(adding, lambda: _add(adding, anna.id, "ben"))
        assert waiting(step)  # on ben's account lock
        deletion.commit()
        with pytest.raises(ApiError) as refused:
            finished(step)
        assert refused.value.status == 404
        adding.rollback()
    assert _rows(migrated) == 0


def test_a_deletion_that_waits_for_an_add_removes_the_contact(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    from tests.concurrency import finished, race, waiting

    with race(migrated) as r:
        adding, deletion = r.first, r.second
        assert _add(adding, anna.id, "ben")

        def delete() -> None:
            account_deletion.lock_account(deletion, ben.id)
            account_deletion.delete_account(deletion, anna.client.app.state.settings, ben.id)  # type: ignore[attr-defined]

        step = r.run(deletion, delete)
        assert waiting(step)  # behind the add's shared lock
        adding.commit()
        finished(step)
        deletion.commit()
    assert _rows(migrated) == 0


@pytest.mark.parametrize(
    ("column", "value"), [("suspended_at", "now"), ("account_status", "pending")]
)
def test_removing_tells_nobody_else_that_an_account_is_not_active(
    anna: flow.Human,
    ben: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    column: str,
    value: str,
) -> None:
    """A suspended or pending account answers `DELETE` as `GET /people` does, `not_found`,
    except to the one who has it as a contact (#1532 review)."""
    cleo = flow.human(make_client, migrated, "cleo")
    put(anna, "ben")
    _set_human(migrated, ben.id, **{column: clock.now() if value == "now" else value})
    assert remove(cleo, "ben").status_code == 404  # never added: same as an unknown name
    assert remove(cleo, "nobody-here").status_code == 404
    assert remove(anna, "ben").status_code == 204  # her contact: she can always remove it
    assert remove(anna, "ben").status_code == 404  # and then it is not hers any more
    assert _rows(migrated) == 0


def test_a_stranger_gets_one_answer_for_every_name_that_is_not_an_active_person(
    anna: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Suspended, pending, deleted and unknown answer `PUT` and `DELETE` alike for someone
    who has none of them as a contact (#1532 review)."""
    states: dict[str, dict[str, Any]] = {
        "sus": {"suspended_at": clock.now()},
        "pen": {"account_status": "pending"},
        "del": {"deleted_at": clock.now()},
    }
    for handle, values in states.items():
        _set_human(migrated, flow.human(make_client, migrated, handle).id, **values)
    for call in (put, remove):
        answers = {
            name: (r.status_code, r.json())
            for name in ("sus", "pen", "del", "nobody-here")
            for r in [call(anna, name)]
        }
        assert len(set(map(str, answers.values()))) == 1, answers
        assert answers["nobody-here"][0] == 404


def test_two_people_adding_each_other_first_both_succeed(
    anna: flow.Human, ben: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Neither has an `account_lock` row yet. Each `PUT` holds its caller's lock and then
    reaches for the other's at the same moment: both get theirs, nobody deadlocks (#1532
    review, delta 1)."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("a race needs two writers: PostgreSQL or MariaDB (CI)")
    with migrated.begin() as conn:
        conn.execute(delete(t.account_lock).where(t.account_lock.c.human_id.in_([anna.id, ben.id])))
    meet = threading.Barrier(2, timeout=10)
    first = {anna.id, ben.id}  # each caller's first hold is its change's transaction
    guard = threading.Lock()
    hold = write_guard.hold

    def held(conn: Any, human_id: str) -> None:
        hold(conn, human_id)
        with guard:
            waits = human_id in first
            first.discard(human_id)
        if waits:
            meet.wait()  # both hold their own lock; now each reaches for the other's

    monkeypatch.setattr(write_guard, "hold", held)
    answers: dict[str, int] = {}

    def adds(who: flow.Human, other: str) -> None:
        answers[who.handle] = put(who, other).status_code

    workers = [
        threading.Thread(target=adds, args=(anna, "ben")),
        threading.Thread(target=adds, args=(ben, "anna")),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
    assert answers == {"anna": 204, "ben": 204}
    assert _rows(migrated) == 2
