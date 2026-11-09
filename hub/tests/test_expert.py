"""docs/api.md §2.3 "The expert": it answers and posts, takes no card and files no request."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def expert(make_client: ClientFactory, owner: flow.Human) -> flow.Agent:
    return flow.agent(make_client, owner, role="expert", areas=["docs/"])


def _card(owner: flow.Human, **body: Any) -> Any:
    return owner.post(f"{PROJECT}/tasks", {"title": "A card", "kind": "task", **body})


def _invalid(response: Any, field: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == {field: "expert"}


def test_an_expert_claims_notes_and_asks_nothing_but_posts(
    owner: flow.Human, expert: flow.Agent
) -> None:
    card = _card(owner).json()["id"]
    assert expert.get(f"{PROJECT}/tasks/{card}").status_code == 200
    assert expert.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 403
    assert expert.post(f"{PROJECT}/tasks/{card}/notes", {"body": "Looks off."}).status_code == 403
    assert expert.post(f"{PROJECT}/tasks", {"title": "Mine"}).status_code == 403
    asked = expert.post(f"{PROJECT}/requests", {"class": "info", "title": "Why?", "to": "owner"})
    assert asked.status_code == 403
    posted = expert.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "§2.3 says so."},
    )
    assert posted.status_code == 201, posted.text


def test_an_expert_answers_a_question_to_the_experts(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent
) -> None:
    asker = flow.agent(make_client, owner)
    asked = asker.post(
        f"{PROJECT}/requests",
        {"class": "info", "title": "Which § says who answers?", "to": "role:expert"},
    )
    assert asked.status_code == 201, asked.text
    request = asked.json()["id"]
    mine = expert.get(f"{PROJECT}/requests", params={"to": "me"}).json()["items"]
    assert [item["id"] for item in mine] == [request]
    answered = expert.post(f"{PROJECT}/requests/{request}/answer", {"text": "§7, the `to` row."})
    assert answered.status_code == 200, answered.text
    assert answered.json()["answer"]["text"] == "§7, the `to` row."


def test_no_card_is_assigned_to_an_expert(owner: flow.Human, expert: flow.Agent) -> None:
    _invalid(_card(owner, assigned_to=expert.id), "assigned_to")
    card = _card(owner).json()["id"]
    _invalid(owner.post(f"{PROJECT}/tasks/{card}/assign", {"assignee": expert.id}), "assignee")
    _invalid(owner.post(f"{PROJECT}/tasks/{card}/claim", {"holder": expert.id}), "holder")
    _invalid(owner.patch(f"{PROJECT}/tasks/{card}", {"assigned_to": expert.id}), "assigned_to")


def test_area_routing_skips_an_expert(owner: flow.Human, expert: flow.Agent) -> None:
    created = _card(owner, area="docs/api.md")
    assert created.status_code == 201, created.text
    assert created.json()["assigned_to"] == owner.id  # "/" is the owner's, not the expert's


def test_a_holder_becomes_an_expert_only_after_its_cards_go_back(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§2.3 "The expert": the role change waits until the member holds no card, and a holder
    without `tasks:write` writes nothing to a card it still holds."""
    coder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert coder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["details"] == {"reason": "holds_cards"}
    # A holder whose role took the work away (here written past the API, as an older
    # membership could hold it) neither checkpoints nor reports.
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == coder.id)
            .values(role="expert", role_base="expert")
        )
    step = {"last_step": "read", "next_step": "write"}
    for path, body in (
        ("checkpoint", step),
        ("report", {"summary": "Done.", "pr_status": "none", "code": False}),
    ):
        refused = coder.post(f"{PROJECT}/tasks/{card}/{path}", body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == coder.id)
            .values(role="coder", role_base="coder")
        )
    released = coder.post(f"{PROJECT}/tasks/{card}/release", {})
    assert released.status_code == 200, released.text
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 200, changed.text


def test_a_role_change_to_expert_that_waits_for_a_go_is_refused_while_cards_are_held(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """§2.3 "The expert": a role change an admin agent proposes is refused at once while
    the member holds a card, not filed as a request that no go could write."""
    admin = flow.agent(make_client, owner, role="admin")
    reviewer = flow.agent(make_client, owner, role="reviewer")
    card = _card(owner).json()["id"]
    assert reviewer.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    refused = admin.patch(f"{PROJECT}/members/{reviewer.id}", {"role": "expert"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"] == {"reason": "holds_cards"}


@pytest.mark.parametrize("status", ["cancelled", "done"])
def test_an_expert_reports_on_no_closed_card(
    owner: flow.Human, expert: flow.Agent, migrated: Engine, status: str
) -> None:
    """§6.4: a report needs `tasks:write`, checked before the card's status."""
    card = _card(owner).json()["id"]
    with migrated.begin() as conn:  # closed past the API, the way a card ends anyhow
        conn.execute(update(t.card).where(t.card.c.id == card).values(status=status))
    body = {"summary": "Done.", "pr_status": "none", "code": False}
    refused = expert.post(f"{PROJECT}/tasks/{card}/report", body)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "tasks:write"}


def test_an_expert_arbiter_moves_its_contract_to_final_and_nothing_else(
    owner: flow.Human, expert: flow.Agent
) -> None:
    """§2.3 "The expert" and §6.8: the arbiter's state move needs no `tasks:write`; every
    other edit of the card still does."""
    created = _card(owner, kind="contract", contract={"arbiter": expert.id})
    assert created.status_code == 201, created.text
    path = f"{PROJECT}/tasks/{created.json()['id']}"
    for body in ({"title": "Mine now"}, {"contract": {"state": "final", "watchers": []}}):
        refused = expert.patch(path, body)
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    final = expert.patch(path, {"contract": {"state": "final"}})
    assert final.status_code == 200, final.text
    assert final.json()["contract"]["state"] == "final"


@pytest.mark.parametrize("entry", ["member", "role:expert"])
def test_an_expert_is_no_substitute(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent, entry: str
) -> None:
    """§6.12: a guest, a proxy or an expert never covers."""
    covered = flow.agent(make_client, owner)
    named = expert.id if entry == "member" else entry
    refused = owner.patch(
        f"{PROJECT}/members/{covered.id}",
        {"availability_policy": {"on_unavailable": "substitute", "substitutes": [named]}},
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "availability_policy.substitutes": "expert"
    }


def test_no_takeover_moves_a_card_to_an_expert(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent
) -> None:
    """§6.19: the receiver `to` is never an expert."""
    holder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    refused = owner.post(
        f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours", "to": expert.id}
    )
    _invalid(refused, "to")


def test_the_receiver_of_an_open_takeover_does_not_become_an_expert(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """§2.3 "The expert", §6.19: an open takeover would move the card to its receiver."""
    holder = flow.agent(make_client, owner)
    receiver = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    opened = receiver.post(f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours"})
    assert opened.status_code == 201, opened.text
    changed = owner.patch(f"{PROJECT}/members/{receiver.id}", {"role": "expert"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["details"] == {"reason": "holds_cards"}


def test_a_member_assigned_an_open_card_does_not_become_an_expert(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    """§2.3 "The expert": an assignment without a claim is a card too; it goes elsewhere
    first."""
    coder = flow.agent(make_client, owner)
    card = _card(owner, assigned_to=coder.id)
    assert card.status_code == 201, card.text
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["details"] == {"reason": "holds_cards"}
    done = owner.patch(f"{PROJECT}/tasks/{card.json()['id']}", {"status": "cancelled"})
    assert done.status_code == 200, done.text
    changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
    assert changed.status_code == 200, changed.text


def test_a_takeover_to_a_member_that_became_an_expert_moves_nothing(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§2.3 "The expert", §6.19: the transfer checks the receiver's role when it writes;
    written past the API here, as the role change itself waits for the takeover."""
    holder = flow.agent(make_client, owner)
    receiver = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    opened = receiver.post(f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours"})
    assert opened.status_code == 201, opened.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == receiver.id)
            .values(role="expert", role_base="expert")
        )
    holder.post(f"{PROJECT}/takeovers/{opened.json()['id']}/respond", {"accept": True})
    taken = owner.get(f"{PROJECT}/takeovers/{opened.json()['id']}").json()
    assert taken["status"] == "cancelled"
    held = owner.get(f"{PROJECT}/tasks/{card}").json()
    assert held["claim"]["holder"] == holder.id and held["assigned_to"] != receiver.id


def _paused(monkeypatch: pytest.MonkeyPatch, where: str, module: Any = None) -> tuple[Any, Any]:
    """Pause the first call of `<module>.<where>` (`routes.tasks` by default) until
    released; returns (reached, release), two events. The route runs in the app's worker
    thread, so the pause holds that request's transaction open at exactly that point."""
    import threading

    from maity_hub.routes import tasks as tasks_route

    if module is None:
        module = tasks_route
    reached, release = threading.Event(), threading.Event()
    real = getattr(module, where)
    armed = [True]

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if armed[0]:
            armed[0] = False
            reached.set()
            assert release.wait(10), "never released"
        return real(*args, **kwargs)

    monkeypatch.setattr(module, where, wrapper)
    return reached, release


def _in_thread(fn: Any) -> Any:
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    pool.shutdown(wait=False)
    return future


def test_a_claim_in_flight_takes_no_card_once_its_member_became_an_expert(
    make_client: ClientFactory,
    owner: flow.Human,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2.3 "The expert": the claim read its membership as a coder; the role change to
    expert commits before the claim takes the project lock. Under the lock the claim reads
    its row again and has no `tasks:write`."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises the two transactions; the race needs PostgreSQL")
    coder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    reached, release = _paused(monkeypatch, "_locked")
    claim = _in_thread(lambda: coder.post(f"{PROJECT}/tasks/{card}/claim", {}))
    try:
        assert reached.wait(10), "the claim never reached the lock"
        changed = owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
        assert changed.status_code == 200, changed.text  # no card yet
    finally:
        release.set()
    refused = claim.result(timeout=10)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    assert owner.get(f"{PROJECT}/tasks/{card}").json()["claim"] is None


def test_a_role_change_to_expert_waits_for_a_claim_in_flight_and_then_refuses(
    make_client: ClientFactory,
    owner: flow.Human,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§2.3 "The expert": the claim has written its holder under the project lock and not
    committed; the role change takes the same lock before its check, so it waits, then
    sees the claim and writes nothing. Without that lock the change passes its check,
    writes the role and only then meets the claim, a deadlock the database breaks by
    rolling it back for a retry: `apply_patch` would have run."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises the two transactions; the race needs PostgreSQL")
    from concurrent.futures import TimeoutError as Pending

    from maity_hub.routes import members as members_route

    written: list[str] = []
    real_apply = members_route.apply_patch

    def apply_patch(*args: Any, **kwargs: Any) -> Any:
        written.append("apply_patch")
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(members_route, "apply_patch", apply_patch)
    coder = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    reached, release = _paused(monkeypatch, "_card")  # read right after the claim's write
    claim = _in_thread(lambda: coder.post(f"{PROJECT}/tasks/{card}/claim", {}))
    change = None
    try:
        assert reached.wait(10), "the claim never wrote"
        change = _in_thread(
            lambda: owner.patch(f"{PROJECT}/members/{coder.id}", {"role": "expert"})
        )
        with pytest.raises(Pending):
            change.result(timeout=1)  # held at the project lock the claim holds
    finally:
        release.set()
    assert claim.result(timeout=10).status_code == 200
    assert change is not None
    refused = change.result(timeout=10)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["details"] == {"reason": "holds_cards"}
    assert written == []  # refused at the check, never written and rolled back


def test_a_takeover_in_flight_to_its_caller_opens_none_once_the_caller_became_an_expert(
    make_client: ClientFactory,
    owner: flow.Human,
    monkeypatch: pytest.MonkeyPatch,
    migrated: Engine,
) -> None:
    """§2.3 "The expert", §6.19: a takeover without `to` goes to the caller itself. The
    route read the caller's membership as a coder; the role change to expert commits before
    the route takes the project lock. Under the lock the route reads the row again and has
    no `tasks:write`, so no takeover opens to an expert."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises the two transactions; the race needs PostgreSQL")
    from maity_hub import takeovers

    holder = flow.agent(make_client, owner)
    caller = flow.agent(make_client, owner)
    card = _card(owner).json()["id"]
    assert holder.post(f"{PROJECT}/tasks/{card}/claim", {}).status_code == 200
    reached, release = _paused(monkeypatch, "settle", takeovers)  # before the lock
    opened = _in_thread(
        lambda: caller.post(f"{PROJECT}/tasks/{card}/takeover", {"reason": "silent for hours"})
    )
    try:
        assert reached.wait(10), "the takeover never reached the lock"
        changed = owner.patch(f"{PROJECT}/members/{caller.id}", {"role": "expert"})
        assert changed.status_code == 200, changed.text  # nothing on the way yet
    finally:
        release.set()
    refused = opened.result(timeout=10)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "tasks:write"}
    assert owner.get(f"{PROJECT}/takeovers").json()["items"] == []


# --- an expert's fields (§2.3 "The expert", §6.2) -------------------------------------------


def _fields(who: Any, member_id: str, **body: Any) -> Any:
    return who.patch(f"{PROJECT}/members/{member_id}", body)


def test_the_owner_names_what_its_expert_answers_about_and_from_which_sources(
    owner: flow.Human, expert: flow.Agent
) -> None:
    """§6.2: `expert_for` and `expert_sources` on the membership, shown in the member view,
    and `null` clears them."""
    changed = _fields(
        owner,
        expert.id,
        expert_for="  The API contract,\n its sections  ",
        expert_sources=["docs/api.md", "context/", "docs/api.md"],
    )
    assert changed.status_code == 200, changed.text
    view = changed.json()
    assert view["expert_for"] == "The API contract, its sections"  # plain text, one line
    assert view["expert_sources"] == ["docs/api.md", "context/"]
    listed = owner.get(f"{PROJECT}/members").json()["items"]
    [shown] = [m for m in listed if m["id"] == expert.id]
    assert (shown["expert_for"], shown["expert_sources"]) == (
        "The API contract, its sections",
        ["docs/api.md", "context/"],
    )
    cleared = _fields(owner, expert.id, expert_for=None, expert_sources=None)
    assert cleared.status_code == 200, cleared.text
    assert (cleared.json()["expert_for"], cleared.json()["expert_sources"]) == (None, [])


def test_only_an_expert_has_the_fields_and_a_role_change_away_clears_them(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent
) -> None:
    """§6.2: the fields belong to the role."""
    coder = flow.agent(make_client, owner)
    refused = _fields(owner, coder.id, expert_for="The API")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"expert_for": "expert_only"}
    assert (
        _fields(owner, expert.id, expert_for="The API", expert_sources=["docs/"]).status_code == 200
    )
    moved = owner.patch(f"{PROJECT}/members/{expert.id}", {"role": "coder"})
    assert moved.status_code == 200, moved.text
    assert (moved.json()["expert_for"], moved.json()["expert_sources"]) == (None, [])
    back = owner.patch(f"{PROJECT}/members/{expert.id}", {"role": "expert"})
    assert (back.json()["expert_for"], back.json()["expert_sources"]) == (None, [])


def test_who_sets_an_experts_fields(
    make_client: ClientFactory, owner: flow.Human, expert: flow.Agent, migrated: Engine
) -> None:
    """§6.2: a human who owns the agent or holds `members:admin`, the fields alone; an
    agent never."""
    assert expert.patch(f"{PROJECT}/members/{expert.id}", {"expert_for": "x"}).status_code == 403
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    member = flow.human(make_client, migrated, "colleague")
    factory.membership(migrated, project_id, "member", human_id=member.id)
    admin = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    assert _fields(admin, expert.id, expert_for="The API").status_code == 200
    refused = _fields(member, expert.id, expert_for="The API")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"scope": "members:admin"}
    mixed = _fields(owner, expert.id, expert_for="The API", areas=["docs/"])
    assert mixed.status_code == 400, mixed.text
    assert mixed.json()["error"]["details"]["fields"] == {"expert_for": "alone"}


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"expert_sources": ["../etc"]}, "expert_sources", "invalid_path"),
        ({"expert_sources": ["docs/a b"]}, "expert_sources", "invalid_path"),
        ({"expert_sources": [f"d{n}/" for n in range(21)]}, "expert_sources", None),
        ({"expert_for": "x" * 121}, "expert_for", None),
    ],
)
def test_an_experts_fields_are_bounded(
    owner: flow.Human, expert: flow.Agent, body: dict[str, Any], field: str, code: str | None
) -> None:
    """§6.2: at most 120 characters and 20 sources, each a repository path."""
    refused = _fields(owner, expert.id, **body)
    assert refused.status_code == 400, refused.text
    fields = refused.json()["error"]["details"]["fields"]
    assert field in fields and (code is None or fields[field] == code)


def test_a_field_write_in_flight_is_cleared_by_a_role_change_away_from_expert(
    owner: flow.Human,
    expert: flow.Agent,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.2: the fields exist only while the role is expert. The role change read the expert
    with empty fields; a field PATCH commits before the change writes. The change takes the
    project lock the field PATCH takes, reads the row again and clears what is there now,
    instead of comparing against the empty fields it read first."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises the two transactions; the race needs PostgreSQL")
    from maity_hub.routes import members as members_route

    reached, release = _paused(monkeypatch, "validate_assignment", members_route)
    change = _in_thread(lambda: owner.patch(f"{PROJECT}/members/{expert.id}", {"role": "coder"}))
    try:
        assert reached.wait(10), "the role change never reached its check"
        written = _fields(owner, expert.id, expert_for="Racing name", expert_sources=["docs/"])
        assert written.status_code == 200, written.text
    finally:
        release.set()
    changed = change.result(timeout=10)
    assert changed.status_code == 200, changed.text
    view = owner.get(f"{PROJECT}/members/{expert.id}").json()
    assert (view["role"], view["expert_for"], view["expert_sources"]) == ("coder", None, [])


def test_a_field_write_waits_for_a_role_change_away_from_expert_and_then_refuses(
    owner: flow.Human,
    expert: flow.Agent,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other order: the role change has written and not committed. It holds the project
    lock, so the field PATCH waits there, then reads the new role and writes nothing, in one
    run."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises the two transactions; the race needs PostgreSQL")
    from concurrent.futures import TimeoutError as Pending

    from maity_hub.routes import members as members_route

    runs: list[str] = []
    real_fields = members_route._expert_fields

    def counted(*args: Any, **kwargs: Any) -> Any:
        runs.append("fields")
        return real_fields(*args, **kwargs)

    monkeypatch.setattr(members_route, "_expert_fields", counted)
    # Held after the change's write, before its commit: `member_view` runs after the UPDATE.
    reached, release = _paused(monkeypatch, "member_view", members_route)
    change = _in_thread(lambda: owner.patch(f"{PROJECT}/members/{expert.id}", {"role": "coder"}))
    field = None
    try:
        assert reached.wait(10), "the role change never wrote"
        field = _in_thread(lambda: _fields(owner, expert.id, expert_for="Too late"))
        with pytest.raises(Pending):
            field.result(timeout=1)  # held at the project lock the change holds
    finally:
        release.set()
    assert change.result(timeout=10).status_code == 200
    assert field is not None
    refused = field.result(timeout=10)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"expert_for": "expert_only"}
    view = owner.get(f"{PROJECT}/members/{expert.id}").json()
    assert (view["role"], view["expert_for"]) == ("coder", None)
    # Once: without the shared lock the field write held the project lock and waited for the
    # member's row, the change then waited for the project lock, and the database broke that
    # deadlock by rolling the field write back for a retry.
    assert runs == ["fields"]
