"""docs/api.md §6.1 `looking_for_coders`, `outside_claims`, `outside_claims_max` and "What the
project allows"; §6.4 `open_to_outsiders` and `claim_requests` (tsk-5q5emh2nm61k, slice A):
the policy fields, the card field and the claim request's read shape. Nothing here files,
confirms or declines a claim request; an outsider's agent still claims no card itself (§6.5,
"Until the claim request is built")."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, outsiders, probe, public_cards, public_pages
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_outsider_join import _outside_agent

P = "/projects/maintainer/maity"
TASKS = f"{P}/tasks"
CONTRIBUTION = f"{P}/contribution"
FIELDS = ("looking_for_coders", "outside_claims", "outside_claims_max")


@pytest.fixture
def make_client(make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch) -> ClientFactory:
    """A hub that serves public pages, without its probe or public-pages worker, as in
    tests/test_outsider_join.py."""
    monkeypatch.setattr(probe.Worker, "start", lambda self: None)
    monkeypatch.setattr(public_pages.Worker, "start", lambda self: None)
    return lambda **kw: make_client(**{"public_pages": True, **kw})


@pytest.fixture
def on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The outsiders' join switched on for the test, so an agent with trust `outside` comes
    from the real join and exchange, never from a raw insert."""
    monkeypatch.setattr(outsiders, "JOINS_ON", True)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity", public_page="on")
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "maity")
        ).scalar_one()
    return found


def _set(who: Any, reason: str | None = "outsiders", **policy: Any) -> Any:
    body: dict[str, Any] = {"policy": policy}
    if reason is not None:
        body["reason"] = reason
    return who.patch(P, body)


def _policy(who: Any) -> dict[str, Any]:
    found = who.get(P)
    assert found.status_code == 200, found.text
    shown: dict[str, Any] = found.json()["policy"]
    return shown


def _fields(response: Any) -> dict[str, Any]:
    assert response.status_code == 400, response.text
    fields: dict[str, Any] = response.json()["error"]["details"]["fields"]
    return fields


def _reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def _human(make_client: ClientFactory, engine: Engine, handle: str, trust: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, _project_id(engine), "coder", trust=trust, human_id=human.id)
    return human


def test_the_switch_is_still_off_on_main() -> None:
    """The guard: this slice opens nothing to outsiders; their join stays switched off."""
    assert outsiders.JOINS_ON is False


# --- the policy fields (§6.1) ---------------------------------------------------------------


def test_the_three_fields_take_their_values_and_refuse_others(owner: flow.Human) -> None:
    assert _fields(_set(owner, looking_for_coders="some")) == {
        "policy.looking_for_coders": "unknown"
    }
    assert _fields(_set(owner, outside_claims="anyone")) == {"policy.outside_claims": "unknown"}
    wrong_caps: tuple[Any, ...] = (0, -1, "2", True, False, 1.5, 2_147_483_648, 10**20, [], {})
    for wrong in wrong_caps:
        assert _fields(_set(owner, outside_claims_max=wrong)) == {
            "outside_claims_max": "out_of_range"
        }, wrong
    for looking in ("per_card", "all", "off"):
        done = _set(owner, looking_for_coders=looking)
        assert done.status_code == 200, done.text
        assert done.json()["policy"]["looking_for_coders"] == looking
    for claims in ("human", "agent", "direct"):
        done = _set(owner, outside_claims=claims)
        assert done.status_code == 200, done.text
        assert done.json()["policy"]["outside_claims"] == claims
    for cap in (1, 2_147_483_647, None):  # null is no cap
        done = _set(owner, outside_claims_max=cap)
        assert done.status_code == 200, done.text
        assert done.json()["policy"]["outside_claims_max"] == cap


def test_a_refused_field_leaves_the_whole_policy_as_it_was(owner: flow.Human) -> None:
    before = _policy(owner)
    assert _set(owner, looking_for_coders="all", outside_claims_max=0).status_code == 400
    assert _policy(owner) == before


NOT_A_CHOICE: tuple[Any, ...] = (None, 1, 0, True, False, 1.5, [], ["all"], {}, {"x": "all"})


@pytest.mark.parametrize("field", ["looking_for_coders", "outside_claims"])
def test_null_and_a_value_that_is_no_string_are_unknown(owner: flow.Human, field: str) -> None:
    """The row's choices only (§6.1): an explicit `null` is no left-out field, and a number, a
    bool, a list or an object is `unknown` as a wrong string is, never `string_type`."""
    before = _policy(owner)
    for wrong in NOT_A_CHOICE:
        assert _fields(_set(owner, **{field: wrong})) == {f"policy.{field}": "unknown"}, wrong
    assert _policy(owner) == before


@pytest.mark.parametrize("field", ["looking_for_coders", "outside_claims"])
def test_a_bad_choice_beside_a_good_field_applies_nothing(
    owner: flow.Human, migrated: Engine, field: str
) -> None:
    """One bad field refuses the whole PATCH: the valid field beside it, the project's name
    and the other choice stay as they were, and no `policy_changed` is written."""
    other = "outside_claims" if field == "looking_for_coders" else "looking_for_coders"
    good = {"looking_for_coders": "all", "outside_claims": "human"}[other]
    before = owner.get(P).json()
    with migrated.connect() as conn:
        events = conn.execute(select(t.event.c.seq).where(t.event.c.kind == "policy_changed")).all()
    for wrong in NOT_A_CHOICE:
        body = {
            "name": "Renamed",
            "reason": "outsiders",
            "policy": {field: wrong, other: good, "outside_claims_max": 5},
        }
        refused = owner.patch(P, body)
        assert _fields(refused) == {f"policy.{field}": "unknown"}, wrong
        assert owner.get(P).json() == before, wrong
    with migrated.connect() as conn:
        after = conn.execute(select(t.event.c.seq).where(t.event.c.kind == "policy_changed")).all()
    assert after == events


def test_null_on_the_cap_removes_it_and_applies_with_the_rest(owner: flow.Human) -> None:
    """`outside_claims_max: null` is the row's no cap (§6.1), deliberately not refused: it
    clears a stored cap, and the other fields of the same PATCH apply with it."""
    assert _set(owner, outside_claims_max=3).status_code == 200
    done = _set(owner, outside_claims_max=None, looking_for_coders="off")
    assert done.status_code == 200, done.text
    shown = _policy(owner)
    assert (shown["outside_claims_max"], shown["looking_for_coders"]) == (None, "off")
    # A bad cap beside a good choice applies nothing, as a bad choice does.
    refused = _set(owner, outside_claims_max=False, looking_for_coders="all")
    assert _fields(refused) == {"outside_claims_max": "out_of_range"}
    assert _policy(owner) == shown


def test_each_change_is_stored_with_its_reason(owner: flow.Human, migrated: Engine) -> None:
    for field, value in zip(FIELDS, ("off", "agent", 2), strict=True):
        missing = _set(owner, None, **{field: value})
        assert _fields(missing) == {"reason": "required"}, field
    done = _set(owner, "open two cards", looking_for_coders="all", outside_claims_max=2)
    assert done.status_code == 200, done.text
    with migrated.connect() as conn:
        changed = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.kind == "policy_changed")
            .order_by(t.event.c.seq.desc())
        ).first()
    assert changed is not None
    assert changed.payload["reason"] == "open two cards"
    old, new = changed.payload["old"], changed.payload["new"]
    assert (old["looking_for_coders"], old["outside_claims_max"]) == ("per_card", None)
    assert (new["looking_for_coders"], new["outside_claims_max"]) == ("all", 2)


def test_a_preset_change_keeps_all_three(owner: flow.Human) -> None:
    done = _set(owner, looking_for_coders="off", outside_claims="direct", outside_claims_max=4)
    assert done.status_code == 200, done.text
    changed = _set(owner, preset="solo")
    assert changed.status_code == 200, changed.text
    shown = changed.json()["policy"]
    assert [shown[f] for f in FIELDS] == ["off", "direct", 4]


def test_a_project_that_predates_the_fields_reads_the_defaults(
    owner: flow.Human, migrated: Engine
) -> None:
    """Null columns, as every project the migration found: `per_card`, `human`, no cap; a
    later write of another field stores the defaults it read."""
    with migrated.begin() as conn:
        conn.execute(
            update(t.project).values(
                looking_for_coders=None, outside_claims=None, outside_claims_max=None
            )
        )
    shown = _policy(owner)
    assert [shown[f] for f in FIELDS] == ["per_card", "human", None]
    assert owner.get(CONTRIBUTION).json()["looking_for_coders"] == "per_card"
    assert _set(owner, badge="members").status_code == 200
    with migrated.connect() as conn:
        stored = conn.execute(
            select(
                t.project.c.looking_for_coders,
                t.project.c.outside_claims,
                t.project.c.outside_claims_max,
            )
        ).one()
    assert tuple(stored) == ("per_card", "human", None)


# --- who sets them ----------------------------------------------------------------------------


def test_agent_and_direct_are_the_owners_and_human_back_is_an_admins(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`owner_only` before any write, the rest of the body included (§6.1, §1.3); `human`
    back is no owner's call alone (the lead's ruling of 2026-11-25, Q9)."""
    admin = _human(make_client, migrated, "admin-human", "admin")
    for value in ("agent", "direct"):
        before = _policy(owner)
        refused = _set(admin, outside_claims=value, looking_for_coders="all")
        assert refused.status_code == 403, refused.text
        assert _reason(refused) == "owner_only"
        assert _policy(owner) == before  # nothing of the call took effect
    assert _set(owner, outside_claims="direct").status_code == 200
    back = _set(admin, outside_claims="human")
    assert back.status_code == 200, back.text
    assert back.json()["policy"]["outside_claims"] == "human"
    # The stored value named again is still a body that sets it: the owner's alone.
    assert _set(owner, outside_claims="agent").status_code == 200
    again = _set(admin, outside_claims="agent")
    assert (again.status_code, _reason(again)) == (403, "owner_only")
    # The other two are any project:admin human's.
    done = _set(admin, looking_for_coders="off", outside_claims_max=3)
    assert done.status_code == 200, done.text


def test_per_human_who_sets_the_three_fields(
    on: None, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Every kind of member on every field: humans with trust owner and admin set them (the
    owner alone `agent` and `direct`); a member and a guest human lack `project:admin`; no
    agent sets any of them, an admin agent and an outsider's agent included (`humans_only`)."""
    outside = _outside_agent(make_client, owner, flow.human(make_client, migrated, "stranger"))
    admin = _human(make_client, migrated, "admin-human", "admin")
    member = _human(make_client, migrated, "member-human", "member")
    guest = _human(make_client, migrated, "guest-human", "guest")
    admin_agent = flow.agent(make_client, owner, role="admin")
    coder_agent = flow.agent(make_client, owner)
    values: dict[str, Any] = {
        "looking_for_coders": "all",
        "outside_claims": "direct",
        "outside_claims_max": 2,
    }
    for field, value in values.items():
        assert _set(owner, **{field: value}).status_code == 200, field
        admin_answer = _set(admin, **{field: value})
        if field == "outside_claims":
            assert (admin_answer.status_code, _reason(admin_answer)) == (403, "owner_only")
        else:
            assert admin_answer.status_code == 200, (field, admin_answer.text)
        for human in (member, guest):
            refused = _set(human, **{field: value})
            assert refused.status_code == 403, (field, human.handle, refused.text)
            assert refused.json()["error"]["details"].get("scope") == "project:admin"
        for agent in (admin_agent, coder_agent, outside):
            refused = _set(agent, **{field: value})
            assert (refused.status_code, _reason(refused)) == (403, "humans_only"), field


def test_the_owner_sets_them_at_creation(owner: flow.Human) -> None:
    made = owner.post(
        "/projects",
        {
            "slug": "second",
            "name": "Second",
            "policy": {"outside_claims": "agent", "looking_for_coders": "off"},
        },
    )
    assert made.status_code == 201, made.text
    shown = made.json()["policy"]
    assert [shown[f] for f in FIELDS] == ["off", "agent", None]


# --- the card field (§6.4) --------------------------------------------------------------------


def _card(who: Any, **body: Any) -> Any:
    return who.post(TASKS, {"title": "A card", **body})


def test_a_card_reads_false_and_the_creator_sets_it(owner: flow.Human, migrated: Engine) -> None:
    plain = _card(owner)
    assert plain.status_code == 201, plain.text
    assert plain.json()["open_to_outsiders"] is False
    assert plain.json()["claim_requests"] == []
    opened = _card(owner, open_to_outsiders=True)
    assert opened.status_code == 201, opened.text
    assert opened.json()["open_to_outsiders"] is True
    history = owner.get(f"{TASKS}/{opened.json()['id']}/history").json()["items"]
    assert history[-1]["field"] == "created"
    assert history[-1]["after"]["open_to_outsiders"] is True
    plain_history = owner.get(f"{TASKS}/{plain.json()['id']}/history").json()["items"]
    assert "open_to_outsiders" not in plain_history[-1]["after"]  # the default, as no label


def test_whoever_edits_the_card_sets_it_and_the_history_records_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The creator, the holder and `tasks:admin` (§6.4, as `label`); anyone else is refused."""
    creator = flow.agent(make_client, owner)
    holder = flow.agent(make_client, owner)
    stranger = flow.agent(make_client, owner)
    made = _card(creator)
    assert made.status_code == 201, made.text
    card = made.json()["id"]
    assert creator.patch(f"{TASKS}/{card}", {"open_to_outsiders": True}).status_code == 200
    claimed = holder.post(f"{TASKS}/{card}/claim", {})
    assert claimed.status_code == 200, claimed.text
    held = holder.patch(f"{TASKS}/{card}", {"open_to_outsiders": False})
    assert held.status_code == 200, held.text
    assert held.json()["open_to_outsiders"] is False
    admin = owner.patch(f"{TASKS}/{card}", {"open_to_outsiders": True})
    assert admin.status_code == 200 and admin.json()["open_to_outsiders"] is True
    refused = stranger.patch(f"{TASKS}/{card}", {"open_to_outsiders": False})
    assert refused.status_code == 403, refused.text
    entries = [
        (e["field"], e["before"], e["after"])
        for e in owner.get(f"{TASKS}/{card}/history").json()["items"]
        if e["field"] == "open_to_outsiders"
    ]
    assert entries == [
        ("open_to_outsiders", False, True),
        ("open_to_outsiders", True, False),
        ("open_to_outsiders", False, True),
    ]
    with migrated.connect() as conn:
        updated = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.kind == "task_updated")
            .order_by(t.event.c.seq.desc())
        ).first()
    assert updated is not None
    assert updated.payload["fields"] == ["open_to_outsiders"]
    assert updated.payload["open_to_outsiders"] is True


def test_a_value_that_is_not_a_boolean_is_invalid(owner: flow.Human) -> None:
    card = _card(owner).json()["id"]
    wrongs: list[Any] = ["true", 1, 0, None, [], {}]
    for wrong in wrongs:
        assert _fields(_card(owner, open_to_outsiders=wrong)) == {
            "open_to_outsiders": "bool_type"
        }, wrong
        assert _fields(owner.patch(f"{TASKS}/{card}", {"open_to_outsiders": wrong})) == {
            "open_to_outsiders": "bool_type"
        }, wrong


def test_an_outsiders_agent_never_names_it(
    on: None, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`outside_trust` for `true` and for `false`, on POST and on PATCH, on a card it created
    and on one it holds, with nothing of the call written (§6.4, §2.3 "Outside")."""
    outside = _outside_agent(make_client, owner, flow.human(make_client, migrated, "stranger"))
    with migrated.connect() as conn:
        cards_before = conn.execute(select(t.card.c.id)).all()
    for value in (True, False):
        refused = _card(outside, open_to_outsiders=value)
        assert (refused.status_code, _reason(refused)) == (403, "outside_trust"), refused.text
    with migrated.connect() as conn:
        assert conn.execute(select(t.card.c.id)).all() == cards_before
    own = _card(outside, title="Its own")
    assert own.status_code == 201, own.text
    handed = _card(owner, title="Handed to it")
    assert handed.status_code == 201, handed.text
    claim = owner.post(f"{TASKS}/{handed.json()['id']}/claim", {"holder": outside.id})
    assert claim.status_code == 200, claim.text
    for card in (own.json()["id"], handed.json()["id"]):
        for value in (True, False):
            refused = outside.patch(
                f"{TASKS}/{card}", {"open_to_outsiders": value, "title": "Renamed"}
            )
            assert (refused.status_code, _reason(refused)) == (403, "outside_trust")
            read = owner.get(f"{TASKS}/{card}").json()
            assert read["title"] != "Renamed" and read["open_to_outsiders"] is False
        # The counter-check: the same agent edits the card without the field.
        assert outside.patch(f"{TASKS}/{card}", {"title": "Renamed"}).status_code == 200
    # Even a value that is not a boolean is the trust's refusal, not a validation answer.
    refused = outside.patch(f"{TASKS}/{own.json()['id']}", {"open_to_outsiders": "yes"})
    assert (refused.status_code, _reason(refused)) == (403, "outside_trust")
    with migrated.connect() as conn:
        cards_before = conn.execute(select(t.card.c.id)).all()
    for wrong in ("yes", 1, None):  # so on POST, and nothing is created
        refused = _card(outside, open_to_outsiders=wrong)
        assert (refused.status_code, _reason(refused)) == (403, "outside_trust"), wrong
    with migrated.connect() as conn:
        assert conn.execute(select(t.card.c.id)).all() == cards_before


def test_claim_requests_is_the_hubs_alone(owner: flow.Human) -> None:
    card = _card(owner).json()["id"]
    for answer in (
        _card(owner, claim_requests=[]),
        owner.patch(f"{TASKS}/{card}", {"claim_requests": []}),
    ):
        assert _fields(answer) == {"claim_requests": "extra_forbidden"}


# --- claim_requests on the card (§6.4) --------------------------------------------------------


def _request(engine: Engine, card: str, member_id: int, *, pending: bool) -> str:
    """A claim request row as slice B will file one: nothing in this slice writes it."""
    request_id = new_id("claim_request")
    now = clock.now()
    with engine.begin() as conn:
        owner_id = conn.execute(
            select(t.agent_profile.c.owner_id)
            .select_from(t.membership.join(t.agent_profile))
            .where(t.membership.c.id == member_id)
        ).scalar_one()
        project_id = conn.execute(
            select(t.card.c.project_id).where(t.card.c.id == card)
        ).scalar_one()
        conn.execute(
            insert(t.claim_request).values(
                id=request_id,
                project_id=project_id,
                task_id=card,
                member_id=member_id,
                instance="wle2",
                owner_id=owner_id,
                status="pending" if pending else "declined",
                pending=True if pending else None,
                reason=None if pending else "not_a_fit",
                requested_at=now,
                lapses_at=now + timedelta(minutes=60),
            )
        )
    return request_id


def _membership_id(engine: Engine, agent_id: str) -> int:
    with engine.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
            )
        ).scalar_one()
    return found


def test_the_waiting_request_reads_in_the_contract_shape_and_a_settled_one_not(
    on: None, owner: flow.Human, make_client: ClientFactory, migrated: Engine, settings: Any
) -> None:
    """`[{id, member_id, instance, requested_at}]` for every reader, an outsider included;
    `decided_by` and `reason` never; the public HTML card shows none of it (the lead's
    ruling of 2026-11-25, Q14)."""
    stranger = flow.human(make_client, migrated, "stranger")
    outside = _outside_agent(make_client, owner, stranger)
    card = _card(owner, open_to_outsiders=True).json()["id"]
    member_id = _membership_id(migrated, outside.id)
    _request(migrated, card, member_id, pending=False)
    assert owner.get(f"{TASKS}/{card}").json()["claim_requests"] == []
    waiting = _request(migrated, card, member_id, pending=True)
    for reader in (owner, outside, stranger):
        shown = reader.get(f"{TASKS}/{card}")
        assert shown.status_code == 200, shown.text
        (only,) = shown.json()["claim_requests"]
        assert set(only) == {"id", "member_id", "instance", "requested_at"}
        assert (only["id"], only["member_id"], only["instance"]) == (waiting, outside.id, "wle2")
        # A `clr-` id and the hub's time to the second (§1.2; the lead's ruling Q18).
        assert only["id"].startswith("clr-")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", only["requested_at"])
    listed = owner.get(TASKS).json()["items"]
    assert [c["claim_requests"] for c in listed if c["id"] == card][0][0]["id"] == waiting
    with migrated.connect() as conn:
        pages = public_cards.render_card(conn, replace(settings, public_pages=True), card)
    assert pages, "the card has a public page"
    assert "claim_requests" not in pages[0].data
    assert waiting not in pages[0].body


# --- what the project allows (§6.1, `…/contribution`) ----------------------------------------


def test_contribution_reads_the_two_settings_and_open_cards_stays_zero(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """`looking_for_coders` and `outside_claims` as the policy reads them; `open_cards` stays
    `0` while the interim of §6.5 holds, whatever the setting and the cards say."""
    stranger = flow.human(make_client, migrated, "stranger")
    first = stranger.get(CONTRIBUTION)
    assert first.status_code == 200, first.text
    assert list(first.json()) == [
        "agent_owners",
        "outside_roles",
        "looking_for_coders",
        "outside_claims",
        "open_cards",
        "agents_max",
        "can_join",
        "reason",
    ]
    assert (first.json()["looking_for_coders"], first.json()["outside_claims"]) == (
        "per_card",
        "human",
    )
    assert _card(owner, open_to_outsiders=True).status_code == 201
    assert _set(owner, looking_for_coders="all", outside_claims="direct").status_code == 200
    now = stranger.get(CONTRIBUTION).json()
    assert (now["looking_for_coders"], now["outside_claims"], now["open_cards"]) == (
        "all",
        "direct",
        0,
    )
    assert now["reason"] == "members_only"  # the switch is off
    assert owner.get(CONTRIBUTION).json()["looking_for_coders"] == "all"  # a member reads it
