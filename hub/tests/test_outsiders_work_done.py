"""docs/api.md §2.3 "Own approvals", §6.4, §6.6 (B.2 of §6.30), tsk-nvsxwd4tzzg9: a report
with a new head on a `done` card of outsiders' work takes the card back to `review`, its claim
kept; and an outside agent holds no done authority through a role that reviews or tests, and
signs no approval, whatever role it is given."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import cards
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError
from tests import flow
from tests.conftest import ClientFactory
from tests.test_own_approvals_gate import (
    OTHER,
    PROJECT,
    _card,
    _count,
    _done,
    _outside,
    _policy,
    _reported,
    _review,
    _row,
    _status,
)
from tests.test_probe import SHA, _report


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


# --- a new head on a done card ---------------------------------------------------------------


def _closed(owner: flow.Human, reporter: Any) -> tuple[str, dict[str, Any]]:
    """A card `reporter` holds and reported on head SHA with pull request #7 open, moved to
    `done` by the owner (`done_authority: admin`, set before the agents join), whose own move
    counts as its approval."""
    card_id = _card(owner)
    _reported(reporter, card_id)
    done = _done(owner, card_id)
    assert done.status_code == 200, done.text
    view: dict[str, Any] = owner.get(f"{PROJECT}/tasks/{card_id}").json()
    assert view["status"] == "done" and view["closed_at"] is not None
    return card_id, view


def _new_head(reporter: Any, card_id: str, head: str = OTHER, **more: Any) -> dict[str, Any]:
    pr = {"number": 7, "url": "https://github.com/acme/maity/pull/7", "head": head, "state": "open"}
    again = reporter.post(
        f"{PROJECT}/tasks/{card_id}/report",
        _report(head=head, remote_head=head, pr=pr, **more),
    )
    assert again.status_code == 200, again.text
    view: dict[str, Any] = again.json()
    return view


def _status_events(engine: Engine, card_id: str) -> list[Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.kind == "task_updated", t.event.c.subject_id == card_id)
            .order_by(t.event.c.seq)
        ).scalars()
        return [p for p in rows if p.get("fields") == ["status"]]


@pytest.mark.parametrize("done", [False, True])
def test_a_new_head_takes_outsiders_work_back_to_review_with_its_claim(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, done: bool
) -> None:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id, before = _closed(owner, outsider)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    _review(reviewer, card_id)  # an own approval on the old head
    assert _count(migrated, card_id) == 1
    statuses = len(_status_events(migrated, card_id))
    after = _new_head(outsider, card_id, done=done)
    assert after["status"] == "review"
    assert after["closed_at"] is None
    assert after["claim"] == before["claim"] and after["claim"] is not None
    assert after["report"]["head"] == OTHER
    assert _count(migrated, card_id) == 0  # the old head's approval counts nothing here
    moved = _status_events(migrated, card_id)[statuses:]
    assert [e["status"] for e in moved] == ["review"]


def test_a_new_head_on_an_own_members_done_card_leaves_it_done(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin")
    agent = flow.agent(make_client, owner)
    card_id, before = _closed(owner, agent)
    after = _new_head(agent, card_id)
    assert after["report"]["head"] == OTHER
    assert {k: after[k] for k in ("status", "closed_at", "claim")} == {
        k: before[k] for k in ("status", "closed_at", "claim")
    }


def test_the_same_head_reported_again_on_outsiders_work_leaves_it_done(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="admin")
    outsider = _outside(make_client, migrated, owner)
    card_id, before = _closed(owner, outsider)
    after = _new_head(outsider, card_id, head=SHA, summary="Rebased, same head.")
    assert after["report"]["summary"] == "Rebased, same head."
    assert {k: after[k] for k in ("status", "closed_at", "claim")} == {
        k: before[k] for k in ("status", "closed_at", "claim")
    }


# --- an outside agent holds no done authority and signs nothing --------------------------------


def _outside_reviewer(
    make_client: ClientFactory, engine: Engine, owner: flow.Human, how: str
) -> Any:
    """An agent with role `reviewer` (trust `member`) that counts as outside: marked
    `joined_outside` while its owner, the project's owner, is a member; or one whose owner is
    no member."""
    if how == "owner_no_member":
        return _outside(make_client, engine, owner, role="reviewer")
    agent = flow.agent(make_client, owner, role="reviewer")
    row = _row(engine, agent.id)
    with engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.id == row).values(joined_outside=True)
        )
    return agent


def _own_work(owner: flow.Human, make_client: ClientFactory, creator: Any = None) -> str:
    """A card an own agent reported: not outsiders' work, so no own-approvals gate applies.
    `creator` files it (an editor of the card, §6.4), else the owner."""
    made = (creator or owner).post(f"{PROJECT}/tasks", {"title": "A card"})
    assert made.status_code == 201, made.text
    card_id: str = made.json()["id"]
    _reported(flow.agent(make_client, owner), card_id)
    return card_id


def _refused_as(answer: Any, expected: Any) -> None:
    """Refused exactly as `expected`, the same call by a member without the scope."""
    assert answer.status_code == expected.status_code == 403, answer.text
    assert answer.json()["error"]["details"] == expected.json()["error"]["details"]


@pytest.mark.parametrize("authority", ["reviewer", "reviewer_and_tester"])
@pytest.mark.parametrize("how", ["joined_outside", "owner_no_member"])
def test_an_outside_reviewer_holds_no_done_authority(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, how: str, authority: str
) -> None:
    _policy(owner, done_authority=authority)
    judge = _outside_reviewer(make_client, migrated, owner, how)
    coder = flow.agent(make_client, owner)
    approve = {"approve": "review"} if authority == "reviewer_and_tester" else {}
    card_id = _own_work(owner, make_client)
    _refused_as(_done(judge, card_id, **approve), _done(coder, card_id))
    rework = {"status": "in_progress"}
    _refused_as(
        judge.patch(f"{PROJECT}/tasks/{card_id}", rework),
        coder.patch(f"{PROJECT}/tasks/{card_id}", rework),
    )
    assert _status(owner, card_id) == "review"


@pytest.mark.parametrize("how", ["joined_outside", "owner_no_member"])
def test_an_outside_reviewer_signs_no_approval_on_a_card_it_filed(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, how: str
) -> None:
    """As the card's creator it may edit the card, so only the done authority and the
    signature decide: refused as a member without `tasks:review` is (§6.4)."""
    _policy(owner, done_authority="reviewer_and_tester")
    judge = _outside_reviewer(make_client, migrated, owner, how)
    card_id = _own_work(owner, make_client, creator=judge)
    signed = _done(judge, card_id, approve="review")
    assert signed.status_code == 403, signed.text
    assert signed.json()["error"]["details"] == {"scope": "tasks:review"}
    view = owner.get(f"{PROJECT}/tasks/{card_id}").json()
    assert view["status"] == "review"
    assert not (view.get("approvals") or {}).get("review")


@pytest.mark.parametrize("how", ["joined_outside", "owner_no_member", "member"])
def test_the_signature_itself_refuses_an_outside_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, how: str
) -> None:
    """`cards.sign` refuses on its own, whatever path calls it, as for a missing scope; a
    member reviewer's signature is given."""
    _policy(owner, done_authority="reviewer_and_tester")
    if how == "member":
        judge = flow.agent(make_client, owner, role="reviewer")
    else:
        judge = _outside_reviewer(make_client, migrated, owner, how)
    row_id = _row(migrated, judge.id)
    with migrated.begin() as conn:
        project = conn.execute(select(t.project)).one()
        row = conn.execute(select(t.membership).where(t.membership.c.id == row_id)).one()
        mine = Membership(project=project, row=row, kind="agent")
        unsigned = SimpleNamespace(approvals=None)
        if how == "member":
            signed = cards.sign(conn, mine, unsigned, "review", 1)
            assert signed["review"]["by"] == judge.id
            return
        with pytest.raises(ApiError) as refused:
            cards.sign(conn, mine, unsigned, "review", 1)
    assert (refused.value.status, refused.value.code) == (403, "forbidden")
    assert refused.value.details == {"scope": "tasks:review"}


def _now_outside(make_client: ClientFactory, engine: Engine, agent: Any, how: str) -> None:
    """The agent, a member's until now, counts as outside from here on: marked
    `joined_outside`, or its profile given to a human who is no member."""
    if how == "joined_outside":
        row = _row(engine, agent.id)
        with engine.begin() as conn:
            conn.execute(
                update(t.membership).where(t.membership.c.id == row).values(joined_outside=True)
            )
        return
    stranger = flow.human(make_client, engine, f"left-{agent.id[-6:]}")
    with engine.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == agent.id)
            .values(owner_id=stranger.id)
        )


def _second_signature(owner: flow.Human, make_client: ClientFactory, card_id: str) -> str:
    """A member tester signs `test`; the card's status after it."""
    tester = flow.agent(make_client, owner, role="tester")
    signed = _done(tester, card_id, approve="test")
    assert signed.status_code == 200, signed.text
    status: str = signed.json()["status"]
    return status


@pytest.mark.parametrize("how", ["joined_outside", "owner_no_member"])
def test_a_stored_signature_of_an_agent_now_outside_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, how: str
) -> None:
    """A `review` signature stored on the card (as one given before outside agents were
    refused): its signer is outside now, so the second signature does not complete
    `approvals` and the card stays in `review`."""
    _policy(owner, done_authority="reviewer_and_tester")
    judge = flow.agent(make_client, owner, role="reviewer")
    card_id = _own_work(owner, make_client)
    mark = {"by": judge.id, "at": "2026-11-23T10:00:00Z", "revision": 1}
    with migrated.begin() as conn:
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card_id)
            .values(approvals={"review": mark, "test": None})
        )
    _now_outside(make_client, migrated, judge, how)
    assert _second_signature(owner, make_client, card_id) == "review"


@pytest.mark.parametrize("how", ["joined_outside", "owner_no_member"])
def test_a_signature_drops_when_its_signer_becomes_outside(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, how: str
) -> None:
    _policy(owner, done_authority="reviewer_and_tester")
    judge = flow.agent(make_client, owner, role="reviewer")
    card_id = _own_work(owner, make_client)
    signed = _done(judge, card_id, approve="review")
    assert signed.status_code == 200, signed.text
    _now_outside(make_client, migrated, judge, how)
    assert _second_signature(owner, make_client, card_id) == "review"


def test_a_members_stored_signature_still_counts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer_and_tester")
    judge = flow.agent(make_client, owner, role="reviewer")
    card_id = _own_work(owner, make_client)
    assert _done(judge, card_id, approve="review").status_code == 200
    assert _second_signature(owner, make_client, card_id) == "done"


def test_a_member_reviewer_keeps_its_done_authority_and_its_signature(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    _policy(owner, done_authority="reviewer")
    card_id = _own_work(owner, make_client)
    assert _done(flow.agent(make_client, owner, role="reviewer"), card_id).status_code == 200
    assert _status(owner, card_id) == "done"
    _policy(owner, done_authority="reviewer_and_tester")
    card_id = _card(owner)
    _reported(flow.agent(make_client, owner), card_id)
    signed = _done(flow.agent(make_client, owner, role="reviewer"), card_id, approve="review")
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "review"  # one of two signatures
