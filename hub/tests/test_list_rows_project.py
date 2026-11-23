"""A project's own lists cost the same statements for 3 rows as for 30 (tests/list_rows.py):
invitations, joins, the jour fixe, a member's briefings and credentials, the project's
messages, takeovers, a card's history and notes, the ticker.

Where the API limits how fast rows come (a join, a series, a takeover per card), one row is
made through the API and the rest are copies of it with new ids, written directly: the list
reads them as it reads the first."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import timedelta
from itertools import count
from typing import Any

import pytest
from sqlalchemy import Engine, Table, insert, select

from maity_hub import clock, ids
from maity_hub import tables as t
from maity_hub.routes import ticker as ticker_routes
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.list_rows import flat_rows, same_for_3_and_30
from tests.test_jour_fixe import answer, ensure_series, grant, listen, start
from tests.test_project_messages import say
from tests.test_takeovers import _held, _open

P = "/projects/maintainer/maity"
_STEP = count(1)


@pytest.fixture(autouse=True)
def _own_steps() -> None:
    """`_STEP` from 1 in every test: which reporter, author or status a row gets by it then
    depends on the test alone, not on how many rows the tests before it made (an overview of
    3 rows without a human reporter read the reporting humans only at 30, 11 against 12)."""
    global _STEP
    _STEP = count(1)


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _membership(engine: Engine, member_id: str) -> int:
    """The membership of an agent (`agt-…`) or a human, in the one project."""
    c = t.membership.c
    with engine.connect() as conn:
        found: int = conn.execute(
            select(c.id).where((c.agent_id == member_id) | (c.human_id == member_id))
        ).scalar_one()
    return found


def _copies(
    engine: Engine, table: Table, row_id: Any, n: int, change: Callable[[int], dict[str, Any]]
) -> None:
    """n copies of the row `row_id` of `table`, each with a new id of the same prefix and the
    values `change(i)` gives the i-th, i counting on over every call."""
    with engine.begin() as conn:
        row = conn.execute(select(table).where(table.c.id == row_id)).mappings().one()
        prefix = str(row_id).split("-", 1)[0]
        for _ in range(n):
            i = next(_STEP)
            new_id = f"{prefix}-{''.join(secrets.choice(ids.CROCKFORD) for _ in range(12))}"
            conn.execute(insert(table).values({**row, "id": new_id, **change(i)}))


@flat_rows("/projects/{}/{}/invitations")
def test_invitations_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    made = owner.post(f"{P}/invitations", {})
    assert made.status_code == 201, made.text
    first = made.json()["id"]
    others = [factory.human(migrated, f"inviter-{n}") for n in range(3)]

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.invitation,
            first,
            n,
            lambda i: {
                "token_hash": secrets.token_hex(32),
                "created_by": others[i % 3],
                "created_at": clock.now() + timedelta(seconds=i),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/invitations",
        lambda: owner.get(f"{P}/invitations?limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/joins")
def test_joins_cost_the_same_for_3_and_for_30(owner: flow.Human, migrated: Engine) -> None:
    flow.join(owner, "maity")
    with migrated.connect() as conn:
        first = conn.execute(select(t.join_link.c.id)).scalar_one()
    others = [factory.human(migrated, f"joiner-{n}") for n in range(3)]
    for human_id in others:
        factory.membership(migrated, _project_id(migrated), "admin", human_id=human_id)

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.join_link,
            first,
            n,
            lambda i: {
                "token_hash": secrets.token_hex(32),
                "created_by": others[i % 3],
                "created_at": clock.now() + timedelta(seconds=i),
            },
        )

    same_for_3_and_30(migrated, "/projects/{}/{}/joins", lambda: owner.get(f"{P}/joins"), grow)


def _round(owner: flow.Human, make_client: ClientFactory) -> tuple[str, list[flow.Agent]]:
    """A started round of a series moderated by an admin agent, and the agents present."""
    lead = flow.agent(make_client, owner, role="admin")
    present = [lead, *(flow.agent(make_client, owner) for _ in range(3))]
    for agent in present:
        listen(agent)
    sid = ensure_series(owner)
    assert grant(owner, sid, lead.id).status_code == 201
    started = start(lead, sid)
    assert started.status_code == 201, started.text
    return str(started.json()["id"]), present


@flat_rows("/projects/{}/{}/jour-fixe/series")
def test_jour_fixe_series_cost_the_same_for_3_and_for_30(
    owner: flow.Human, migrated: Engine
) -> None:
    first = ensure_series(owner)
    others = [factory.human(migrated, f"keeper-{n}") for n in range(3)]

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.jour_fixe_series,
            first,
            n,
            lambda i: {
                "topic": f"Topic {i}",
                "created_by": others[i % 3],
                "created_at": clock.now() + timedelta(seconds=i),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/jour-fixe/series",
        lambda: owner.get(f"{P}/jour-fixe/series"),
        grow,
    )


@flat_rows("/projects/{}/{}/jour-fixe/rounds")
def test_jour_fixe_rounds_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A project-wide series read by the project's owner: `circle.reads` answers without a read.
    An owner circle read by another than its owner is measured on its own, below."""
    first, _ = _round(owner, make_client)

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.jour_fixe_round,
            first,
            n,
            lambda i: {
                "status": ("reported", "skipped", "missed")[i % 3],
                "scheduled_for": clock.now() - timedelta(days=i),
                "created_at": clock.now() - timedelta(days=i),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/jour-fixe/rounds",
        lambda: owner.get(f"{P}/jour-fixe/rounds?limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/jour-fixe/rounds")
@pytest.mark.parametrize(
    "case",
    [
        "owner circle, read by the circle owner",
        "owner circle, read by the moderator",
        "owner circle, read by the owned agent",
    ],
)
def test_jour_fixe_rounds_of_an_owner_circle_cost_the_same_for_3_and_for_30(
    case: str, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The rounds of a series for one human's own agents (§20.7), read by that human, by the
    round's moderator and by another of the human's agents: `circle.reads` decides each round,
    and only for its owner without a read (h385 at #2039)."""
    from tests.test_jour_fixe_circle import Circle

    circle = Circle(owner, make_client, migrated, [clock.now()])
    by: dict[str, Any] = {  # the cases as string literals: the guard reads them (GROWING)
        "owner circle, read by the circle owner": circle.friend,
        "owner circle, read by the moderator": circle.lead,
        "owner circle, read by the owned agent": circle.worker,
    }

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.jour_fixe_round,
            circle.id,
            n,
            lambda i: {
                "status": ("reported", "skipped", "missed")[i % 3],
                "scheduled_for": clock.now() - timedelta(days=i),
                "created_at": clock.now() - timedelta(days=i),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/jour-fixe/rounds",
        lambda: by[case].get(f"{P}/jour-fixe/rounds?limit=200"),
        grow,
        case=case,
    )


@flat_rows("/projects/{}/{}/jour-fixe/rounds/{}/answers")
def test_jour_fixe_answers_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    round_id, present = _round(owner, make_client)
    made = answer(present[1], round_id, went_well="Reviews were quick.")
    assert made.status_code == 201, made.text
    first = made.json()["id"]
    authors = [_membership(migrated, agent.id) for agent in present]

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.jour_fixe_answer,
            first,
            n,
            lambda i: {
                "anonymous": i % 2 == 0,
                "author": None if i % 2 == 0 else authors[i % len(authors)],
                "went_well": f"answer {i}",
                "shuffle": secrets.token_hex(32),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/jour-fixe/rounds/{}/answers",
        lambda: owner.get(f"{P}/jour-fixe/rounds/{round_id}/answers"),
        grow,
    )


@flat_rows("/projects/{}/{}/members/{}/briefings")
def test_a_member_s_briefings_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    target = _membership(migrated, agent.id)
    writers = [owner.id, *(factory.human(migrated, f"writer-{n}") for n in range(3)), agent.id]
    with migrated.connect() as conn:  # the join may have stored the first version
        stored = conn.execute(
            select(t.member_briefing.c.version).where(t.member_briefing.c.membership_id == target)
        ).scalars()
        versions = count(max(stored, default=0) + 1)

    def grow(n: int) -> None:
        with migrated.begin() as conn:
            for _ in range(n):
                version = next(versions)
                conn.execute(
                    insert(t.member_briefing).values(
                        membership_id=target,
                        version=version,
                        text=f"briefing {version}",
                        by=writers[version % len(writers)],
                        at=clock.now(),
                    )
                )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/members/{}/briefings",
        lambda: owner.get(f"{P}/members/{agent.id}/briefings"),
        grow,
    )


@flat_rows("/projects/{}/{}/members/{}/credentials")
def test_a_member_s_credentials_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    taken = {agent.instance}

    def grow(n: int) -> None:
        def change(i: int) -> dict[str, Any]:
            instance = ids.new_instance_id(taken)
            taken.add(instance)
            return {
                "instance": instance,
                "created_at": clock.now() + timedelta(seconds=i),
                "last_used_at": clock.now() if i % 2 else None,
            }

        _copies(migrated, t.credential, agent.credential_id, n, change)
        # Each copy in the agent's membership, as the first one is (§6.17).
        a = t.instance_attachment
        with migrated.begin() as conn:
            [membership_id] = set(
                conn.execute(
                    select(a.c.membership_id).where(a.c.credential_id == agent.credential_id)
                ).scalars()
            )
            attached = select(a.c.credential_id)
            for i, copy in enumerate(
                conn.execute(
                    select(t.credential.c.id, t.credential.c.instance).where(
                        t.credential.c.agent_id == agent.id,
                        t.credential.c.id.not_in(attached),
                    )
                ).all()
            ):
                conn.execute(
                    insert(a).values(
                        credential_id=copy.id,
                        membership_id=membership_id,
                        instance=copy.instance,
                        attached_at=clock.now(),
                        dormant_since=clock.now() if i % 3 == 0 else None,
                    )
                )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/members/{}/credentials",
        lambda: owner.get(f"{P}/members/{agent.id}/credentials"),
        grow,
    )


@flat_rows("/projects/{}/{}/messages")
def test_the_project_s_messages_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    writers: list[Any] = [owner, *(flow.agent(make_client, owner) for _ in range(3))]
    sent = count(0)

    def grow(n: int) -> None:
        for _ in range(n):
            i = next(sent)
            say(writers[i % len(writers)], "all", f"message {i}", ("notice", "blocker")[i % 2])

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/messages",
        lambda: owner.get(f"{P}/messages?limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/takeovers")
def test_takeovers_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agents = [flow.agent(make_client, owner) for _ in range(3)]
    card_id = _held(owner, agents[0])
    made = _open(agents[1], card_id)
    assert made.status_code == 201, made.text
    first = made.json()["id"]
    members = [_membership(migrated, agent.id) for agent in agents]
    project_id = _project_id(migrated)
    creator = _membership(migrated, owner.id)

    def grow(n: int) -> None:
        cards = [factory.card(migrated, project_id, creator) for _ in range(n)]

        def change(i: int) -> dict[str, Any]:
            return {
                "task_id": cards.pop(),
                "from_member": members[i % 3],
                "to_member": members[(i + 1) % 3],
                "requested_by": members[(i + 2) % 3],
                "created_at": clock.now() + timedelta(seconds=i),
            }

        _copies(migrated, t.takeover, first, n, change)

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/takeovers",
        lambda: owner.get(f"{P}/takeovers?status=all&limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/tasks/{}/history")
def test_a_card_s_history_costs_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = owner.post(f"{P}/tasks", {"title": "A card"})
    assert card.status_code == 201, card.text
    card_id = card.json()["id"]
    agents = [flow.agent(make_client, owner) for _ in range(3)]
    actors = [_membership(migrated, owner.id), *(_membership(migrated, a.id) for a in agents)]

    def grow(n: int) -> None:
        with migrated.begin() as conn:
            for _ in range(n):
                i = next(_STEP)
                conn.execute(
                    insert(t.card_history).values(
                        id=ids.new_id("history"),
                        card_id=card_id,
                        at=clock.now() + timedelta(seconds=i),
                        actor_membership=actors[i % len(actors)],
                        field="title",
                        before=f"title {i - 1}",
                        after=f"title {i}",
                        redacted=False,
                    )
                )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/tasks/{}/history",
        lambda: owner.get(f"{P}/tasks/{card_id}/history?limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/tasks/{}/notes")
def test_a_card_s_notes_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    card = owner.post(f"{P}/tasks", {"title": "A card"})
    assert card.status_code == 201, card.text
    card_id = card.json()["id"]
    writers: list[Any] = [owner, *(flow.agent(make_client, owner) for _ in range(3))]
    written = count(0)

    def grow(n: int) -> None:
        for _ in range(n):
            i = next(written)
            done = writers[i % len(writers)].post(
                f"{P}/tasks/{card_id}/notes", {"body": f"finding {i}"}
            )
            assert done.status_code == 201, done.text

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/tasks/{}/notes",
        lambda: owner.get(f"{P}/tasks/{card_id}/notes?state=all&limit=200"),
        grow,
    )


@flat_rows("/projects/{}/{}/ticker")
def test_the_ticker_costs_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    enabled = owner.patch(P, {"settings": {"ticker": {"enabled": True}}})
    assert enabled.status_code == 200, enabled.text
    writers = [
        flow.agent(make_client, owner, role="admin", areas=["context/"]),
        flow.agent(make_client, owner, role="admin", areas=["hub/"]),
        flow.agent(make_client, owner, role="admin", areas=["web/"]),
    ]
    posted = count(0)

    def grow(n: int) -> None:
        for _ in range(n):
            i = next(posted)
            ticker_routes.POSTS.reset()
            ticker_routes.POSTS_TO_ALL.reset()
            done = writers[i % 3].post(
                f"{P}/ticker", {"type": "note", "text": f"Note number {i}.", "areas": ["hub/"]}
            )
            assert done.status_code == 201, done.text

    same_for_3_and_30(
        migrated, "/projects/{}/{}/ticker", lambda: owner.get(f"{P}/ticker?limit=200"), grow
    )


@flat_rows("/projects/{}/{}/attachments")
def test_pending_attachments_cost_the_same_for_3_and_for_30(
    make_client: ClientFactory, migrated: Engine, tmp_path: Any
) -> None:
    from maity_hub import attachments
    from tests.test_attachments import put

    blobs = tmp_path / "blobs"
    blobs.mkdir()
    stored: Any = lambda **o: make_client(attachment_dir=blobs, **o)  # noqa: E731
    owner = flow.human(stored, migrated)
    flow.project(owner)
    # At most 20 pending uploads per member: the owner and three agents, the owner reads all.
    uploaders: list[Any] = [owner] + [flow.agent(stored, owner) for _ in range(3)]

    def grow(n: int) -> None:
        for i in range(n):
            attachments.UPLOADS.reset()  # the upload limit, as test_attachments resets it
            attachments.VOLUME.reset()
            who = uploaders[next(_STEP) % len(uploaders)]
            uploaded = put(who, f"note-{i}.txt", b"a pending upload")
            assert uploaded.status_code == 201, uploaded.text

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/attachments",
        lambda: owner.get(f"{P}/attachments?status=pending&limit=200"),
        grow,
    )


def _keyed(key: str) -> Callable[[Any], int]:
    """The rows of a list the answer carries under `key`, not `items`."""

    def rows(answer: Any) -> int:
        found = answer.json()[key]
        assert isinstance(found, list), answer.text
        return len(found)

    return rows


@flat_rows("/projects/{}/{}/jour-fixe")
def test_the_jour_fixe_overview_costs_the_same_for_3_and_for_30_series(
    owner: flow.Human, migrated: Engine
) -> None:
    first = ensure_series(owner)
    others = [factory.human(migrated, f"host-{n}") for n in range(3)]

    def grow(n: int) -> None:
        _copies(
            migrated,
            t.jour_fixe_series,
            first,
            n,
            lambda i: {
                "topic": f"Overview topic {i}",
                "created_by": others[i % 3],
                "created_at": clock.now() + timedelta(seconds=i),
            },
        )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/jour-fixe",
        lambda: owner.get(f"{P}/jour-fixe"),
        grow,
        rows=_keyed("series"),
    )


@flat_rows("/projects/{}/{}/limits")
def test_the_project_s_limits_cost_the_same_for_3_and_for_30_agents(
    owner: flow.Human, migrated: Engine
) -> None:
    project_id = _project_id(migrated)

    def grow(n: int) -> None:
        for _ in range(n):
            factory.agent(migrated, project_id, owner.id)

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/limits",
        lambda: owner.get(f"{P}/limits"),
        grow,
        rows=_keyed("agents"),
    )


@flat_rows("/projects/{}/{}/swarm")
def test_the_swarm_costs_the_same_for_3_and_for_30_members(
    owner: flow.Human, migrated: Engine
) -> None:
    project_id = _project_id(migrated)
    keepers = [factory.human(migrated, f"swarm-owner-{n}") for n in range(3)]

    def grow(n: int) -> None:
        for _ in range(n):
            factory.agent(migrated, project_id, keepers[next(_STEP) % 3])

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/swarm",
        lambda: owner.get(f"{P}/swarm"),
        grow,
        rows=_keyed("members"),
    )


@flat_rows("/projects/{}/{}/overview")
def test_the_overview_s_reports_cost_the_same_for_3_and_for_30(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The latest report of each card, up to `limit` (at most 50): cards reported by the owner
    and three agents."""
    project_id = _project_id(migrated)
    reporters = [owner.id] + [flow.agent(make_client, owner).id for _ in range(3)]
    created_by = _membership(migrated, owner.id)

    made = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            # The reporters by this test's own count, so the first 3 rows already hold a human
            # and agents: by the shared `_STEP`, whether the owner reported one of them hung on
            # the tests that ran before, and the 30 rows' one read of the reporting humans came
            # on top (11 against 12 on PostgreSQL in CI).
            i = next(_STEP)
            reporter = reporters[made[0] % 4]
            made[0] += 1
            factory.card(
                migrated,
                project_id,
                created_by,
                status="review",
                report={
                    "reported_by": reporter,
                    "reported_at": clock.rfc3339(clock.now() + timedelta(seconds=i)),
                    "verification": "tests pass",
                    "pr_status": "found",
                    "pr": {"number": i, "url": f"https://github.com/o/r/pull/{i}"},
                },
            )

    same_for_3_and_30(
        migrated,
        "/projects/{}/{}/overview",
        lambda: owner.get(f"{P}/overview?limit=50"),
        grow,
        rows=_keyed("reports"),
    )
