"""docs/api.md §6.5 and §6.6: claims, leases, release, assign, checkpoint, report."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _claim(who: Any, card: dict[str, Any], **body: Any) -> Any:
    return who.post(f"/projects/maity/tasks/{card['id']}/claim", body)


def _later(seconds: int) -> None:
    start = clock.now()
    clock.set_source(lambda: start + timedelta(seconds=seconds))


# --- claim ---------------------------------------------------------------------------


def test_a_claim_takes_the_card_with_a_lease(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    session = agent.resume().json()["session"]["id"]
    card = task(owner)
    response = _claim(agent, card)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    claim = body["claim"]
    assert (claim["holder"], claim["session_id"], claim["expired"]) == (agent.id, session, False)
    lease = flow_time(claim["lease_until"]) - flow_time(claim["since"])
    assert lease == timedelta(seconds=7200)


def flow_time(text: str) -> Any:
    from tests.factory import at

    return at(text)


def test_only_one_of_many_concurrent_claims_wins(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agents = [flow.agent(make_client, owner) for _ in range(6)]
    card = task(owner)
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda a: _claim(a, card), agents))
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409, 409, 409, 409, 409]
    assert {r.headers.get("Maity-Error") for r in responses if r.status_code == 409} == {
        "already_claimed"
    }
    with migrated.connect() as conn:
        assert conn.execute(select(t.card.c.claim_holder)).scalar() is not None


def test_a_held_card_says_who_holds_it_even_when_expired(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    card = task(owner)
    _claim(a, card)
    _later(7201)
    refused = _claim(b, card)
    assert refused.status_code == 409
    details = refused.json()["error"]["details"]
    assert (details["holder"], details["expired"]) == (a.id, True)


def test_assign_only_projects_hand_cards_out(owner: flow.Human, make_client: ClientFactory) -> None:
    owner.patch("/projects/maity", {"policy": {"claim_policy": "assign-only"}, "reason": "x"})
    agent = flow.agent(make_client, owner)
    card = task(owner)
    assert _claim(agent, card).headers["Maity-Error"] == "assign_only"
    owner.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": agent.id})
    assert _claim(agent, card).status_code == 200


def test_a_proposed_card_is_not_claimable(owner: flow.Human) -> None:
    card = task(owner, status="proposed")
    response = _claim(owner, card)
    assert response.json()["error"]["details"] == {"from": "proposed", "to": "in_progress"}


def test_freeze_wants_a_reason_and_closed_refuses(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = task(owner)
    owner.patch("/projects/maity", {"state": "fixes-only", "reason": "release"})
    assert _claim(owner, card).json()["error"]["details"]["fields"] == {"reason": "required"}
    assert _claim(owner, card, reason="the regression").status_code == 200
    with migrated.connect() as conn:
        payload = conn.execute(
            select(t.event.c.payload).where(t.event.c.kind == "task_claimed")
        ).scalar_one()
    assert (payload["project_state"], payload["reason"]) == ("fixes-only", "the regression")
    other = task(owner, reason="needed")
    owner.patch("/projects/maity", {"state": "accepted", "reason": "shipped"})
    assert _claim(owner, other, reason="x").headers["Maity-Error"] == "project_closed"


def test_an_admin_claims_on_behalf_of_a_member(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    response = _claim(owner, card, holder=agent.id)
    assert response.json()["claim"]["holder"] == agent.id
    member = flow.agent(make_client, owner)
    other = task(owner)
    refused = _claim(member, other, holder=agent.id)
    assert refused.status_code == 403


# --- leases ---------------------------------------------------------------------------


def test_any_call_of_the_holder_renews_and_a_new_session_inherits(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    _claim(agent, card)
    _later(3600)
    agent.get("/me")  # not about the card at all
    claim = owner.get(f"/projects/maity/tasks/{card['id']}").json()["claim"]
    expected = (clock.now() + timedelta(seconds=7200)).replace(microsecond=0)
    assert flow_time(claim["lease_until"]) == expected
    new = agent.resume().json()
    assert [c["id"] for c in new["claims"]] == [card["id"]]
    assert new["claims"][0]["claim"]["session_id"] == new["session"]["id"]


# --- release and assign ---------------------------------------------------------------------


def test_the_holder_releases_and_an_admin_only_after_expiry(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    early = owner.post(f"/projects/maity/tasks/{card['id']}/release", {})
    assert early.status_code == 409 and early.headers["Maity-Error"] == "lease_active"
    stranger = flow.agent(make_client, owner)
    assert stranger.post(f"/projects/maity/tasks/{card['id']}/release", {}).status_code == 403
    released = agent.post(f"/projects/maity/tasks/{card['id']}/release", {})
    assert (released.json()["status"], released.json()["claim"]) == ("open", None)
    _claim(agent, card)
    _later(7201)
    assert owner.post(f"/projects/maity/tasks/{card['id']}/release", {}).json()["claim"] is None


def test_assign_moves_an_expired_claim_and_refuses_an_active_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    card = task(owner)
    _claim(a, card)
    active = owner.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": b.id})
    assert active.headers["Maity-Error"] == "lease_active"
    _later(7201)
    moved = owner.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": b.id}).json()
    assert (moved["assigned_to"], moved["claim"]["holder"], moved["claim"]["expired"]) == (
        b.id,
        b.id,
        False,
    )
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.kind == "task_assigned")).one()
    assert f"member:{a.id}" in event.audience and f"member:{b.id}" in event.audience
    assert (
        a.post(f"/projects/maity/tasks/{card['id']}/assign", {"assignee": a.id}).status_code == 403
    )


# --- checkpoint and report --------------------------------------------------------------


def _signed_post(agent: flow.Agent, path: str, body: dict[str, Any]) -> Any:
    raw = json.dumps(body).encode()
    secret = agent.credential.split(".")[2]
    key = hashlib.sha256(secret.encode()).digest()
    timestamp, nonce = str(int(clock.now().timestamp())), secrets.token_urlsafe(16)
    full = f"/api/v1{path}"
    canonical = "\n".join(
        ["MAITY-HMAC-V1", "POST", full, "", timestamp, nonce, hashlib.sha256(raw).hexdigest()]
    )
    headers = {
        "Authorization": f"Maity-HMAC {agent.credential_id}",
        "Maity-Timestamp": timestamp,
        "Maity-Nonce": nonce,
        "Maity-Signature": hmac.new(key, canonical.encode(), "sha256").hexdigest(),
        "Content-Type": "application/json",
    } | agent.key()
    return agent.client.post(full, content=raw, headers=headers)


def test_a_checkpoint_says_how_it_arrived(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    body = {"last_step": "table", "next_step": "endpoint", "branch": "agent-b/x", "head": "d91e294"}
    bearer = agent.post(f"/projects/maity/tasks/{card['id']}/checkpoint", body).json()
    assert bearer["checkpoint"]["verification"] == "bearer"
    signed = _signed_post(agent, f"/projects/maity/tasks/{card['id']}/checkpoint", body).json()
    assert signed["checkpoint"]["verification"] == "signed"
    assert signed["checkpoint"]["last_step"] == "table" and signed["checkpoint"]["updated_at"]
    with migrated.connect() as conn:
        event = conn.execute(
            select(t.event)
            .where(t.event.c.kind == "task_checkpoint")
            .order_by(t.event.c.seq.desc())
        ).first()
    assert event is not None and event.audience == [f"member:{agent.id}"]
    stranger = flow.agent(make_client, owner)
    refused = stranger.post(f"/projects/maity/tasks/{card['id']}/checkpoint", body)
    assert refused.headers["Maity-Error"] == "not_holder"


def test_a_report_moves_the_card_to_review_and_keeps_the_claim(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    session = agent.resume().json()["session"]["id"]
    card = task(owner)
    _claim(agent, card)
    sha = "d91e294c" + "0" * 32
    pr = {"number": 7, "url": "https://github.com/a/b/pull/7", "head": sha, "state": "open"}
    response = _signed_post(
        agent, f"/projects/maity/tasks/{card['id']}/report", _report(pr=pr, pr_status="found")
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "review" and body["claim"]["holder"] == agent.id
    report = body["report"]
    assert (report["verification"], report["reported_by"], report["session_id"]) == (
        "signed",
        agent.id,
        session,
    )
    assert (report["observed"], report["mismatch"], report["pr"]["number"]) == (None, None, 7)
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.kind == "task_reported")).one()
    assert event.audience == [
        f"member:{agent.id}",
        f"member:{owner.id}",
        "role:reviewer",
        "role:admin",
    ]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"remote_head": "e" * 40}, "remote_head"),
        ({"pr_status": "found"}, "pr_status"),
        ({"pr_status": "unknown"}, "pr_unknown_reason"),
        ({"head": "not-a-sha", "remote_head": "not-a-sha"}, "head"),
        ({"head": "d91e294", "remote_head": "d91e294"}, "head"),
        (
            {
                "pr": {
                    "number": 7,
                    "url": "https://github.com/a/b/pull/7",
                    "head": "d91e294",
                    "state": "open",
                }
            },
            "pr.head",
        ),
    ],
)
def test_a_report_must_agree_with_itself(
    owner: flow.Human, make_client: ClientFactory, overrides: dict[str, Any], field: str
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    response = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(**overrides))
    assert field in response.json()["error"]["details"]["fields"]


def test_done_with_the_report_needs_done_authority_and_closed_dependencies(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    refused = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(done=True))
    assert refused.status_code == 403
    assert (
        owner.get(f"/projects/maity/tasks/{card['id']}").json()["report"] is None
    )  # nothing stored
    owner.patch("/projects/maity", {"policy": {"done_authority": "holder"}, "reason": "solo work"})
    dep = task(owner)
    owner.patch(f"/projects/maity/tasks/{card['id']}", {"depends_on": [dep["id"]]})
    blocked = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(done=True))
    assert blocked.json()["error"]["details"] == {"open": [dep["id"]]}
    owner.patch(f"/projects/maity/tasks/{dep['id']}", {"status": "cancelled"})
    done = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(done=True)).json()
    assert done["status"] == "done" and done["closed_at"]


def test_review_goes_on_by_done_authority(owner: flow.Human, make_client: ClientFactory) -> None:
    """Default preset: done authority is the reviewer's, holder or not (§6.4, PR #23)."""
    agent = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = task(owner)
    _claim(agent, card)
    agent.post(f"/projects/maity/tasks/{card['id']}/report", _report())
    holder_done = agent.patch(f"/projects/maity/tasks/{card['id']}", {"status": "done"})
    assert holder_done.status_code == 403
    assert holder_done.json()["error"]["details"] == {"scope": "tasks:review"}
    rework = reviewer.patch(f"/projects/maity/tasks/{card['id']}", {"status": "in_progress"})
    assert rework.json()["status"] == "in_progress"
    more = reviewer.patch(f"/projects/maity/tasks/{card['id']}", {"status": "done", "title": "x"})
    assert more.status_code == 403  # anything beyond the status stays the editors'
    agent.post(f"/projects/maity/tasks/{card['id']}/report", _report())
    assert (
        reviewer.patch(f"/projects/maity/tasks/{card['id']}", {"status": "done"}).json()["status"]
        == "done"
    )


def test_a_card_may_be_reported_again(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(summary="first"))
    again = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(summary="second"))
    assert again.json()["report"]["summary"] == "second"


# --- review round: decisions under the lock, races, human leases ------------------------


def test_a_claim_decides_from_the_project_as_locked(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A state change committed while the claim waited for the lock wins (§6.5)."""
    from sqlalchemy import update

    from maity_hub import events
    from maity_hub.routes import tasks

    agent = flow.agent(make_client, owner)
    card = task(owner)
    real = events.lock_project

    def accepted_meanwhile(conn: Any, project_id: str) -> Any:
        conn.execute(update(t.project).where(t.project.c.id == project_id).values(state="accepted"))
        return real(conn, project_id)

    monkeypatch.setattr(tasks, "lock_project", accepted_meanwhile)
    response = _claim(agent, card)
    assert response.status_code == 409
    assert response.headers["Maity-Error"] == "project_closed"


def test_crossing_dependencies_never_store_a_cycle(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    for _ in range(5):
        a, b = task(owner), task(owner)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.map(
                lambda pair: owner.patch(
                    f"/projects/maity/tasks/{pair[0]['id']}", {"depends_on": [pair[1]["id"]]}
                ),
                [(a, b), (b, a)],
            )
        statuses = sorted([first.status_code, second.status_code])
        assert statuses == [200, 400], statuses
        with migrated.connect() as conn:
            edges = conn.execute(
                select(t.card_edge.c.from_card, t.card_edge.c.to_card).where(
                    t.card_edge.c.from_card.in_([a["id"], b["id"]])
                )
            ).all()
        assert len(edges) == 1


def test_a_claim_racing_a_cancel_never_answers_500(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    for _ in range(5):
        card = task(owner)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claim_future = pool.submit(_claim, agent, card)
            cancel_future = pool.submit(
                owner.patch, f"/projects/maity/tasks/{card['id']}", {"status": "cancelled"}
            )
            claimed, cancelled = claim_future.result(), cancel_future.result()
        assert claimed.status_code in (200, 409), claimed.text
        assert cancelled.status_code == 200


def test_a_human_holders_calls_renew_its_lease(owner: flow.Human) -> None:
    card = task(owner)
    _claim(owner, card)
    _later(3600)
    owner.get("/me")
    claim = owner.get(f"/projects/maity/tasks/{card['id']}").json()["claim"]
    expected = (clock.now() + timedelta(seconds=7200)).replace(microsecond=0)
    assert flow_time(claim["lease_until"]) == expected


@pytest.mark.parametrize(
    ("path", "body", "field"),
    [
        ("/tasks", {"title": "x", "assigned_to": "agt-nobody"}, "assigned_to"),
        ("/tasks/{id}/claim", {"holder": "agt-nobody"}, "holder"),
        ("/tasks/{id}/assign", {"assignee": "agt-nobody"}, "assignee"),
    ],
)
def test_a_non_member_is_invalid(
    owner: flow.Human, path: str, body: dict[str, Any], field: str
) -> None:
    card = task(owner)
    response = owner.post("/projects/maity" + path.replace("{id}", card["id"]), body)
    assert response.json()["error"]["details"]["fields"] == {field: "not_a_member"}


def test_report_done_without_authority_names_the_scope(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    card = task(owner)
    _claim(agent, card)
    refused = agent.post(f"/projects/maity/tasks/{card['id']}/report", _report(done=True))
    assert refused.json()["error"]["details"] == {"scope": "tasks:review"}
