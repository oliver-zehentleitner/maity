"""docs/api.md §6.26, "Adding a member: by invitation, with their word": an invitation is a
personal consent request without a project, answered by the invited human alone."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select, update

from maity_hub import clock, org_invitations, orgs
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_orgs import delete_org, make_org, team

URL = "/orgs/oz-team/members/invitations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)


def invite(who: flow.Human, handle: str, role: str = "member") -> Any:
    return who.post(URL, {"handle": handle, "role": role})


def requests_of(who: flow.Human, status: str = "open") -> list[dict[str, Any]]:
    got = who.get("/requests", params={"status": status})
    assert got.status_code == 200, got.text
    items: list[dict[str, Any]] = got.json()["items"]
    return items


def later(seconds: float) -> None:
    start = clock.now()
    clock.set_source(lambda: start + timedelta(seconds=seconds))


def request_rows(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.request)).all())


def test_an_invitation_reaches_the_human_as_a_personal_request_with_no_project(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    org = make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    made = invite(owner, "guest", "admin")
    assert made.status_code == 202, made.text
    item = made.json()
    assert item["handle"] == "guest" and item["role"] == "admin"
    assert item["invited_by"] == {"id": owner.id, "handle": "maintainer"}
    assert set(item) == {"id", "handle", "role", "invited_by", "created_at", "expires_at"}
    assert owner.get(URL).json() == {"items": [item]}
    [open_request] = requests_of(guest)
    assert (open_request["project"], open_request["org"]) == (
        None,
        {"id": org["id"], "handle": "oz-team"},
    )
    assert (open_request["class"], open_request["personal"], open_request["status"]) == (
        "consent",
        True,
        "open",
    )
    assert [r["id"] for r in open_request["replies"]] == ["go", "no"]
    assert open_request["asked_by"]["member_id"] == owner.id
    assert "oz-team" in open_request["title"] and "admin" in open_request["title"]
    row = next(r for r in request_rows(migrated) if r.id == open_request["id"])
    assert (row.project_id, row.org_id, row.asked_by, row.asked_by_human) == (
        None,
        org["id"],
        None,
        owner.id,
    )
    read = guest.get(f"/requests/{open_request['id']}")
    assert (read.status_code, read.json()["project"], read.json()["org"]["handle"]) == (
        200,
        None,
        "oz-team",
    )
    counts = guest.get("/me/notifications").json()
    assert counts["counts"]["inbox"] == 1 and counts["by_project"] == {}
    [bell] = [i for i in counts["items"] if i["kind"] == "inbox"]
    assert (bell["kind"], bell["project"], bell["target"]["id"]) == (
        "inbox",
        None,
        open_request["id"],
    )
    # nobody else reads or answers it
    stranger = flow.human(make_client, migrated, "stranger")
    assert stranger.get(f"/requests/{open_request['id']}").status_code == 404
    assert (
        stranger.post(f"/requests/{open_request['id']}/answer", {"reply_id": "go"}).status_code
        == 404
    )
    assert [m["id"] for m in owner.get("/orgs/oz-team/members").json()["items"]] == [owner.id]


def test_go_makes_the_human_a_member_with_the_invited_role(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest", "admin")
    [pending] = requests_of(guest)
    answered = guest.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"})
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "answered"
    assert guest.get("/orgs/oz-team").json()["my_role"] == "admin"
    assert owner.get(URL).json() == {"items": []}
    assert requests_of(guest) == []
    again = guest.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"})
    assert again.status_code == 409
    with migrated.connect() as conn:
        closed = conn.execute(select(t.org_invitation)).one()
        assert (closed.live, closed.closed_by) == (None, "accepted")
    assert guest.get("/me/notifications").json()["counts"]["inbox"] == 0


def test_no_and_the_humans_own_withdrawal_end_the_invitation(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guests = {h: flow.human(make_client, migrated, h) for h in ("first", "second")}
    for handle, how in (("first", "no"), ("second", "withdraw")):
        who = guests[handle]
        assert invite(owner, handle).status_code == 202
        [pending] = requests_of(who)
        if how == "no":
            done = who.post(f"/requests/{pending['id']}/answer", {"reply_id": "no"})
        else:
            done = who.post(f"/requests/{pending['id']}/withdraw", {})
        assert done.status_code == 200, done.text
        assert who.get("/orgs").json() == {"items": []}
    assert owner.get(URL).json() == {"items": []}
    with migrated.connect() as conn:
        reasons = sorted(r.closed_by for r in conn.execute(select(t.org_invitation)).all())
    assert reasons == ["declined", "declined"]


def test_a_handle_that_names_nobody_gets_the_same_answer_and_no_request(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    make_org(owner, "other-org", "Other")
    flow.human(make_client, migrated, "real")
    pending = factory.human(migrated, "pending-one")
    gone = factory.human(migrated, "gone-one")
    with migrated.begin() as conn:
        conn.execute(
            update(t.human).where(t.human.c.id == pending).values(account_status="pending")
        )
        conn.execute(update(t.human).where(t.human.c.id == gone).values(deleted_at=clock.now()))
    answers = {}
    for handle in ("real", "nobody-here", "other-org", "pending-one", "gone-one"):
        made = invite(owner, handle)
        assert made.status_code == 202, (handle, made.text)
        answers[handle] = made.json()
    shapes = {frozenset(a) for a in answers.values()}
    assert len(shapes) == 1
    assert {h: a["handle"] for h, a in answers.items()} == {h: h for h in answers}
    filed = [r for r in request_rows(migrated) if r.org_id is not None]
    assert len(filed) == 1  # only the human who can be invited got a request
    assert len(owner.get(URL).json()["items"]) == 5  # and the others stay open until they expire


def test_what_an_invitation_may_name_and_who_may_send_it(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    flow.human(make_client, migrated, "newbie")
    admin, member = people["admin"], people["member"]
    assert invite(owner, "team-member").json()["error"]["details"]["fields"] == {"handle": "member"}
    assert invite(owner, "Newbie").json()["error"]["details"]["fields"] == {"handle": "invalid"}
    assert invite(owner, "newbie", "boss").json()["error"]["details"]["fields"] == {
        "role": "invalid"
    }
    assert invite(owner, "newbie", "owner").status_code == 202
    assert invite(admin, "newbie").json()["error"]["details"]["fields"] == {"handle": "invited"}
    for refused in (invite(admin, "other", "owner"), invite(member, "other"), member.get(URL)):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"] == {"reason": "org_role"}
    assert invite(admin, "other", "admin").status_code == 202
    stranger = flow.human(make_client, migrated, "stranger")
    assert invite(stranger, "newbie").status_code == 404
    assert stranger.get(URL).status_code == 404
    assert len(owner.get(URL).json()["items"]) == 2


def test_an_owner_revokes_any_invitation_and_an_admin_those_for_member_and_admin(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    guest = flow.human(make_client, migrated, "guest")
    flow.human(make_client, migrated, "other")
    for_owner = invite(owner, "guest", "owner").json()
    for_member = invite(owner, "other", "member").json()
    assert requests_of(guest)
    admin = people["admin"]
    denied = admin.delete(f"{URL}/{for_owner['id']}")
    assert (denied.status_code, denied.json()["error"]["details"]) == (403, {"reason": "org_role"})
    assert admin.delete(f"{URL}/{for_member['id']}").status_code == 204
    assert admin.delete(f"{URL}/{for_member['id']}").status_code == 404
    assert owner.delete(f"{URL}/{for_owner['id']}").status_code == 204
    assert requests_of(guest) == [] and len(requests_of(guest, "withdrawn")) == 1
    assert owner.get(URL).json() == {"items": []}
    assert owner.delete(f"{URL}/inv-unknown").status_code == 404
    again = invite(owner, "guest")  # a revoked value may be offered again
    assert again.status_code == 202


def test_an_inviter_who_loses_the_role_loses_the_invitations_it_allowed(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    for handle in ("g-owner", "g-admin", "g-member"):
        flow.human(make_client, migrated, handle)
    second = people["owner2"]
    invite(second, "g-owner", "owner")
    invite(second, "g-admin", "admin")
    invite(second, "g-member", "member")
    members = "/orgs/oz-team/members"
    demoted = owner.patch(f"{members}/{second.id}", {"role": "admin"})
    assert demoted.status_code == 200
    left = {i["handle"] for i in owner.get(URL).json()["items"]}
    assert left == {"g-admin", "g-member"}  # the one for `owner` goes
    assert owner.patch(f"{members}/{second.id}", {"role": "member"}).status_code == 200
    assert owner.get(URL).json() == {"items": []}
    invite(owner, "g-member", "member")
    assert owner.delete(f"{members}/{owner.id}").status_code == 409  # the only owner stays...
    assert owner.patch(f"{members}/{second.id}", {"role": "owner"}).status_code == 200
    assert owner.delete(f"{members}/{owner.id}").status_code == 204  # ...then leaves
    assert second.get(URL).json() == {"items": []}


def test_deleting_the_organisation_withdraws_its_invitations(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest")
    assert len(requests_of(guest)) == 1
    assert delete_org(owner, "oz-team", "oz-team").status_code == 204
    assert requests_of(guest) == []
    assert len(requests_of(guest, "withdrawn")) == 1
    assert guest.get("/me/notifications").json()["counts"]["inbox"] == 0


def test_an_invitation_expires_after_fourteen_days(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest")
    invite(owner, "nobody-here")
    [pending] = requests_of(guest)
    with migrated.begin() as conn:  # the invitations are 14 days old, one second ago
        conn.execute(update(t.org_invitation).values(expires_at=clock.now() - timedelta(seconds=1)))
    with migrated.begin() as conn:  # the minute worker's work, without waiting for it
        org_invitations.expire(conn)
    assert requests_of(guest) == [] and len(requests_of(guest, "withdrawn")) == 1
    assert guest.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"}).status_code == 409
    assert owner.get(URL).json() == {"items": []}
    with migrated.connect() as conn:
        assert {r.closed_by for r in conn.execute(select(t.org_invitation)).all()} == {"expired"}


def test_an_organisation_files_twenty_invitations_a_day(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    for n in range(20):
        assert invite(owner, f"name-{n:02d}").status_code == 202
    refused = invite(owner, "one-more")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0
    later(24 * 3600 + 1)
    assert invite(owner, "one-more").status_code == 202


def test_the_deleted_accounts_invitations_are_withdrawn(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest")
    with migrated.begin() as conn:
        org_invitations.withdraw_for_human(conn, guest.id, "invitee_deleted")
    assert requests_of(guest) == []
    with migrated.connect() as conn:
        assert conn.execute(select(t.org_invitation.c.closed_by)).scalar_one() == "invitee_deleted"
        assert conn.execute(select(func.count()).select_from(t.org_member)).scalar_one() == 1


def test_the_deletion_of_either_side_withdraws_the_invitations(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    _, people = team(make_client, migrated, owner)
    guest = flow.human(make_client, migrated, "guest")
    other = flow.human(make_client, migrated, "other")
    invite(people["admin"], "guest")
    invite(owner, "other")
    with migrated.begin() as conn:
        # the invited human's own, then the inviter's: the two functions the deletion calls
        org_invitations.withdraw_for_human(conn, guest.id, "invitee_deleted")
        org_invitations.withdraw_by_inviter_everywhere(conn, owner.id, "inviter_deleted")
    assert requests_of(guest) == [] and requests_of(other) == []
    with migrated.connect() as conn:
        reasons = sorted(r.closed_by for r in conn.execute(select(t.org_invitation)).all())
    assert reasons == ["invitee_deleted", "inviter_deleted"]


def test_a_deleted_inviter_is_shown_as_a_deleted_account(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest")
    before = [i for i in guest.get("/me/notifications").json()["items"] if i["kind"] == "inbox"]
    assert "Maintainer" in before[0]["title"] or "maintainer" in before[0]["title"].lower()
    with migrated.begin() as conn:
        conn.execute(update(t.human).where(t.human.c.id == owner.id).values(deleted_at=clock.now()))
    after = [i for i in guest.get("/me/notifications").json()["items"] if i["kind"] == "inbox"]
    assert "Deleted account" in after[0]["title"] and "aintainer" not in after[0]["title"]
    [pending] = requests_of(guest)
    assert pending["asked_by"]["display_name"] == "Deleted account"


def test_a_go_after_the_expiry_withdraws_the_invitation_as_expired(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    """The answer comes after `expires_at` and before the worker's run: a stale `go`, the
    invitation `expired` (not `declined`), the request withdrawn, nobody a member."""
    make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest")
    [pending] = requests_of(guest)
    with migrated.begin() as conn:
        conn.execute(update(t.org_invitation).values(expires_at=clock.now() - timedelta(seconds=1)))
    stale = guest.post(f"/requests/{pending['id']}/answer", {"reply_id": "go"})
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["details"] == {"reason": "invitation_stale"}
    assert requests_of(guest) == [] and len(requests_of(guest, "withdrawn")) == 1
    assert guest.get("/orgs").json() == {"items": []}
    with migrated.connect() as conn:
        closed = conn.execute(select(t.org_invitation)).one()
        assert (closed.live, closed.closed_by) == (None, "expired")
    # and a `no` after the expiry is no decline either
    invite(owner, "guest")
    [again] = requests_of(guest)
    with migrated.begin() as conn:
        conn.execute(
            update(t.org_invitation)
            .where(t.org_invitation.c.live.is_(True))
            .values(expires_at=clock.now() - timedelta(seconds=1))
        )
    assert guest.post(f"/requests/{again['id']}/answer", {"reply_id": "no"}).status_code == 200
    with migrated.connect() as conn:
        reasons = sorted(r.closed_by for r in conn.execute(select(t.org_invitation)).all())
    assert reasons == ["expired", "expired"]


def test_the_first_go_withdraws_the_other_open_invitations_to_the_same_human(
    make_client: ClientFactory, migrated: Engine, owner: flow.Human
) -> None:
    """Two names reach one human (a handle and an alias, §6.24, which come with #523): two open
    invitations, two requests. The first `go` makes them a member with its own role and
    withdraws the other, so a later `go` finds nothing open."""
    org = make_org(owner)
    guest = flow.human(make_client, migrated, "guest")
    invite(owner, "guest", "member")
    with migrated.begin() as conn:  # the second, as an alias would have filed it
        row = conn.execute(select(t.org).where(t.org.c.id == org["id"])).one()
        other_id = "oiv-second"
        request_id = org_invitations._file_request(conn, row, other_id, owner.id, guest.id, "admin")
        conn.execute(
            insert(t.org_invitation).values(
                id=other_id,
                org_id=org["id"],
                handle="guest-alias",
                role="admin",
                invited_by=owner.id,
                request_id=request_id,
                created_at=clock.now(),
                expires_at=clock.now() + timedelta(days=14),
                live=True,
            )
        )
    first, second = sorted(requests_of(guest), key=lambda r: r["title"])
    assert "admin" in first["title"] and "member" in second["title"]
    assert guest.post(f"/requests/{second['id']}/answer", {"reply_id": "go"}).status_code == 200
    assert guest.get("/orgs/oz-team").json()["my_role"] == "member"  # the role it said go to
    assert requests_of(guest) == []
    again = guest.post(f"/requests/{first['id']}/answer", {"reply_id": "go"})
    assert again.status_code == 409  # the other one was withdrawn with the first go
    with migrated.connect() as conn:
        closed = {r.id: r.closed_by for r in conn.execute(select(t.org_invitation)).all()}
    assert (
        sorted(closed.values()) == ["accepted", "superseded"]
        and closed["oiv-second"] == "superseded"
    )


def test_the_workers_expiry_locks_the_organisations_it_touches(
    migrated: Engine, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    locked: list[str] = []
    real = orgs.lock
    make_org(owner)
    make_org(owner, "second-org", "Second")
    for url in (URL, "/orgs/second-org/members/invitations"):
        assert owner.post(url, {"handle": "somebody", "role": "member"}).status_code == 202
    with migrated.begin() as conn:
        conn.execute(update(t.org_invitation).values(expires_at=clock.now() - timedelta(seconds=1)))

    def spy(conn: Any, org_id: str) -> Any:
        locked.append(org_id)
        return real(conn, org_id)

    monkeypatch.setattr(orgs, "lock", spy)
    org_invitations.sweep(migrated)
    assert len(locked) == 2 and locked == sorted(locked)  # both, in the order of their ids
    assert owner.get(URL).json() == {"items": []}
