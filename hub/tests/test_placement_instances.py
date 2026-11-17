"""docs/api.md §15.5, §15.11, §6.12: several placements per agent, one per instance, within
the agent's `max_instances` (tsk-rfa7fwa2sz5g)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.availability import sweep
from tests import flow
from tests.conftest import ClientFactory
from tests.test_join_pickup import exchange, pick_up
from tests.test_placements import REPOSITORY, Setup, allow_instances, place, placed, report
from tests.test_runner_stream import attach, hello
from tests.test_runners import Runner, error, paired
from tests.test_tasks import task

MEMBERS = "/projects/maintainer/maity/members"


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    """A project with an attached runner and an agent joined by hand, `max_instances` 1."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    attach(owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    return Setup(owner, runner, client, agent, migrated)


def second_runner(s: Setup, make_client: ClientFactory) -> Setup:
    """Another runner of the same owner, attached and online: a Setup that places there."""
    runner: Runner = paired(make_client, s.owner, name="office-box")
    attach(s.owner, runner)
    client = make_client()
    assert hello(client, runner).status_code == 200
    return Setup(s.owner, runner, client, s.agent, s.engine)


def handle_of(s: Setup) -> str:
    handle: str = s.owner.get(f"{MEMBERS}/{s.agent.id}").json()["handle"]
    return handle


def started(s: Setup, placement: dict[str, Any], make_client: ClientFactory) -> str:
    """The pickup and its exchange: the instance id the placement now runs."""
    picked = pick_up(s, placement)
    assert picked.status_code == 201, picked.text
    joined = exchange(make_client(), picked.json())
    assert joined.status_code == 201, joined.text
    instance: str = s.owner.get(f"/projects/maintainer/maity/placements/{placement['id']}").json()[
        "instance"
    ]
    return instance


def test_the_instance_limit_refuses_a_placement_at_its_creation(setup: Setup) -> None:
    # The joined clone is the one instance `max_instances: 1` allows.
    refused = place(setup)
    assert (refused.status_code, error(refused)) == (409, "instance_quota")
    assert refused.json()["error"]["details"] == {"max": 1}
    with setup.engine.connect() as conn:
        assert conn.execute(select(t.placement.c.id)).first() is None  # nothing created


def test_a_waiting_placement_counts_toward_the_limit(setup: Setup) -> None:
    allow_instances(setup.engine, setup.agent.id, 2)
    placed(setup)  # no credential yet: it will start the second instance
    refused = place(setup)
    assert (refused.status_code, error(refused)) == (409, "instance_quota")
    allow_instances(setup.engine, setup.agent.id, 3)
    assert place(setup).status_code == 201


def test_two_instances_on_one_runner_get_two_clones(
    setup: Setup, make_client: ClientFactory
) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    first = placed(setup)
    second = placed(setup)  # the member already runs here: placed again, not refused
    assert first["workspace"]["clone"] == handle_of(setup)
    assert second["workspace"]["clone"] == f"{handle_of(setup)}-2"
    assert first["instance"] is None and second["instance"] is None  # before the pickup
    one, two = started(setup, first, make_client), started(setup, second, make_client)
    assert one != two
    member = setup.owner.get(f"{MEMBERS}/{setup.agent.id}").json()
    assert [(p["id"], p["instance"]) for p in member["placements"]] == [
        (first["id"], one),
        (second["id"], two),
    ]
    assert member["placement"]["id"] == first["id"] and "instance" not in member["placement"]
    lines = setup.owner.get(f"/runners/{setup.runner.id}/placements").json()["items"]
    assert sorted(line["instance"] for line in lines) == sorted([one, two])


def test_two_instances_on_two_runners(setup: Setup, make_client: ClientFactory) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    other = second_runner(setup, make_client)
    here, there = placed(setup), placed(other)
    assert here["workspace"]["clone"] == there["workspace"]["clone"] == handle_of(setup)
    assert {here["runner"]["id"], there["runner"]["id"]} == {setup.runner.id, other.runner.id}
    started(setup, here, make_client)
    started(other, there, make_client)
    member = setup.owner.get(f"{MEMBERS}/{setup.agent.id}").json()
    assert {p["runner_name"] for p in member["placements"]} == {"home-laptop", "office-box"}
    assert len({p["instance"] for p in member["placements"]}) == 2


def test_a_named_clone_still_holds_one_placement(setup: Setup) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    placed(setup)
    refused = place(setup, workspace={"clone": handle_of(setup)})
    assert (refused.status_code, error(refused)) == (409, "placement_exists")


def test_the_clone_default_skips_another_members_held_clone(
    setup: Setup, make_client: ClientFactory
) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    handle = handle_of(setup)
    other = flow.agent(
        make_client,
        setup.owner,
        agent={"handle": f"{handle}-2", "display_name": "Another agent"},
        role="member",
    )
    allow_instances(setup.engine, other.id, 2)
    theirs = placed(setup, agent={"id": other.id})
    assert theirs["workspace"]["clone"] == f"{handle}-2"
    assert (
        setup.owner.delete(f"/projects/maintainer/maity/placements/{theirs['id']}").status_code
        == 200
    )
    first, second = placed(setup), placed(setup)
    assert first["workspace"]["clone"] == handle_of(setup)
    # `<handle>-2` is the other agent's clone, closed but not reported removed.
    assert second["workspace"]["clone"] == f"{handle_of(setup)}-3"


def test_one_active_placement_per_credential(setup: Setup, make_client: ClientFactory) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    first, second = placed(setup), placed(setup)
    started(setup, first, make_client)
    credential = setup.owner.get(f"/projects/maintainer/maity/placements/{first['id']}").json()[
        "credential_id"
    ]
    with pytest.raises(IntegrityError), setup.engine.begin() as conn:
        conn.execute(
            update(t.placement)
            .where(t.placement.c.id == second["id"])
            .values(credential_id=credential)
        )


def test_one_running_placement_keeps_the_agent_available(
    setup: Setup, make_client: ClientFactory
) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    first, second = placed(setup), placed(setup)
    for p in (first, second):
        assert report(setup, p, 1).status_code == 200
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    base = clock.now().replace(microsecond=0)
    soon, later = clock.rfc3339(base + timedelta(hours=1)), clock.rfc3339(base + timedelta(hours=3))
    assert report(setup, first, 2, **limited, retry_at=later).status_code == 200

    def availability() -> dict[str, Any]:
        found: dict[str, Any] = setup.owner.get(f"{MEMBERS}/{setup.agent.id}").json()[
            "availability"
        ]
        return found

    assert availability()["state"] != "limited"  # the second one still runs
    assert report(setup, second, 2, **limited, retry_at=soon).status_code == 200
    now = availability()
    assert (now["state"], now["source"], now["until"]) == ("limited", "runner", soon)
    assert report(setup, second, 3).status_code == 200  # it runs again
    assert availability()["state"] != "limited"


def _limit(s: Setup) -> tuple[Any, Any]:
    """The member's stored limit: `until` as the member view shows it, and the placement
    the record names."""
    shown = s.owner.get(f"{MEMBERS}/{s.agent.id}").json()["availability"]
    with s.engine.connect() as conn:
        named = conn.execute(
            select(t.membership.c.limit_placement_id).where(t.membership.c.agent_id == s.agent.id)
        ).scalar_one()
    return (shown.get("until") if shown["state"] == "limited" else None), named


def test_stopping_the_running_placement_leaves_the_limited_one_to_decide(
    setup: Setup,
) -> None:
    """P1 runs and P2 is rate-limited: the agent is available. Stopping P1 recomputes from
    P2 alone, and the record names P2 (§6.12)."""
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    later = clock.rfc3339(clock.now().replace(microsecond=0) + timedelta(hours=2))
    assert report(setup, p1, 1).status_code == 200
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p2, 1, **limited, retry_at=later).status_code == 200
    assert _limit(setup) == (None, None)
    path = f"/projects/maintainer/maity/placements/{p1['id']}"
    assert setup.owner.patch(path, {"desired": "stopped"}).status_code == 200
    assert _limit(setup) == (later, p2["id"])
    # And back: P1 to run again, so it counts again and has not reported a limit.
    assert setup.owner.patch(path, {"desired": "running"}).status_code == 200
    assert _limit(setup) == (None, None)


def test_a_closed_placement_hands_the_limit_to_the_rest(setup: Setup) -> None:
    """Both rate-limited, P1 the earlier: the record names P1. Closing P1 recomputes from
    P2, and closing P2 too leaves no runner limit (§6.12, §15.7 Stopping)."""
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    base = clock.now().replace(microsecond=0)
    soon, later = clock.rfc3339(base + timedelta(hours=1)), clock.rfc3339(base + timedelta(hours=3))
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p2, 1, **limited, retry_at=later).status_code == 200
    assert report(setup, p1, 1, **limited, retry_at=soon).status_code == 200
    assert _limit(setup) == (soon, p1["id"])
    base_path = "/projects/maintainer/maity/placements"
    assert setup.owner.delete(f"{base_path}/{p1['id']}").status_code == 200
    assert _limit(setup) == (later, p2["id"])
    assert setup.owner.delete(f"{base_path}/{p2['id']}").status_code == 200
    assert _limit(setup) == (None, None)


def test_a_tie_on_retry_at_names_the_placement_created_first(setup: Setup) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    same = clock.rfc3339(clock.now().replace(microsecond=0) + timedelta(hours=2))
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p2, 1, **limited, retry_at=same).status_code == 200
    assert report(setup, p1, 1, **limited, retry_at=same).status_code == 200
    assert _limit(setup) == (same, p1["id"])  # not the one that reported last


def test_a_recompute_never_touches_a_limit_the_agent_set_itself(setup: Setup) -> None:
    """§6.12: a recomputation creates, changes or clears only `source: runner`."""
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    base = clock.now().replace(microsecond=0)
    own, later = clock.rfc3339(base + timedelta(hours=5)), clock.rfc3339(base + timedelta(hours=1))
    declared = setup.agent.post("/me/limit", {"until": own, "reason": "my own"})
    assert declared.status_code == 200, declared.text
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p1, 1, **limited, retry_at=later).status_code == 200
    assert report(setup, p2, 1, **limited, retry_at=later).status_code == 200
    shown = setup.owner.get(f"{MEMBERS}/{setup.agent.id}").json()["availability"]
    assert (shown["state"], shown["source"], shown["until"]) == ("limited", "self", own)
    assert report(setup, p1, 2, state="starting").status_code == 200  # not cleared either
    assert _limit(setup) == (own, None)


def _own_until_17_rate_limited_until_18(setup: Setup) -> tuple[Any, str, str]:
    """Two placements rate-limited until 18:00 while the agent's own limit runs until 17:00
    (review A1058): the own limit stands, the record names no placement."""
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    base = clock.now().replace(microsecond=0)
    seventeen = base + timedelta(hours=1)
    eighteen = clock.rfc3339(base + timedelta(hours=2))
    declared = setup.agent.post("/me/limit", {"until": clock.rfc3339(seventeen)})
    assert declared.status_code == 200, declared.text
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p1, 1, **limited, retry_at=eighteen).status_code == 200
    assert report(setup, p2, 1, **limited, retry_at=eighteen).status_code == 200
    assert _limit(setup) == (clock.rfc3339(seventeen), None)
    return seventeen, eighteen, p1["id"]


def _shown(s: Setup) -> tuple[Any, Any, Any]:
    found = s.owner.get(f"{MEMBERS}/{s.agent.id}").json()["availability"]
    return found["state"], found.get("source"), found.get("until")


def test_the_end_of_an_own_limit_at_until_hands_over_to_the_runners(setup: Setup) -> None:
    """§6.12: the end of a self-set limit is a recomputation. Own limit until 17:00, every
    placement rate-limited until 18:00: after 17:00 the agent is limited until 18:00."""
    seventeen, eighteen, first = _own_until_17_rate_limited_until_18(setup)
    clock.set_source(lambda: seventeen + timedelta(seconds=1))
    sweep(setup.engine)
    assert _shown(setup) == ("limited", "runner", eighteen)
    assert _limit(setup) == (eighteen, first)


def test_the_end_of_an_own_limit_by_a_resume_hands_over_to_the_runners(setup: Setup) -> None:
    _, eighteen, first = _own_until_17_rate_limited_until_18(setup)
    assert setup.agent.resume().status_code == 200
    assert _shown(setup) == ("limited", "runner", eighteen)
    assert _limit(setup) == (eighteen, first)


def test_clearing_an_own_limit_hands_over_to_the_runners(setup: Setup) -> None:
    _, eighteen, first = _own_until_17_rate_limited_until_18(setup)
    cleared = setup.agent.post("/me/limit", {"until": None})
    assert cleared.status_code == 200, cleared.text
    assert _shown(setup) == ("limited", "runner", eighteen)
    assert _limit(setup) == (eighteen, first)


def test_clearing_a_runners_limit_recomputes_it(setup: Setup) -> None:
    """§6.12: any `until: null` recomputes. Every placement still rate-limited: the
    runner's limit stays, the agent does not show `available`."""
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    eighteen = clock.rfc3339(clock.now().replace(microsecond=0) + timedelta(hours=2))
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p1, 1, **limited, retry_at=eighteen).status_code == 200
    assert report(setup, p2, 1, **limited, retry_at=eighteen).status_code == 200
    assert _limit(setup) == (eighteen, p1["id"])
    cleared = setup.agent.post("/me/limit", {"until": None})
    assert cleared.status_code == 200, cleared.text
    assert _shown(setup) == ("limited", "runner", eighteen)
    assert _limit(setup) == (eighteen, p1["id"])


def _stalled(s: Setup) -> int:
    with s.engine.connect() as conn:
        return len(conn.execute(select(t.event).where(t.event.c.kind == "holder_stalled")).all())


def test_a_gapless_handover_from_an_own_limit_stalls_the_holder_once(setup: Setup) -> None:
    """The runner's limit taking over from the agent's own at 17:00 is no new start (§6.5,
    §6.12): one `holder_stalled`, from the own limit's start."""
    card = task(setup.owner)
    claimed = setup.agent.post(f"/projects/maintainer/maity/tasks/{card['id']}/claim", {})
    assert claimed.status_code == 200, claimed.text
    seventeen, eighteen, _ = _own_until_17_rate_limited_until_18(setup)
    assert _stalled(setup) == 1
    clock.set_source(lambda: seventeen + timedelta(seconds=1))
    sweep(setup.engine)
    assert _shown(setup) == ("limited", "runner", eighteen)
    assert _stalled(setup) == 1


def test_a_retry_at_that_has_passed_counts_as_running(setup: Setup) -> None:
    allow_instances(setup.engine, setup.agent.id, 3)
    p1, p2 = placed(setup), placed(setup)
    base = clock.now().replace(microsecond=0)
    soon, later = base + timedelta(minutes=10), base + timedelta(hours=3)
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, p1, 1, **limited, retry_at=clock.rfc3339(soon)).status_code == 200
    clock.set_source(lambda: soon + timedelta(seconds=1))
    # P1's retry_at is behind: P2's limit alone does not limit the agent.
    assert report(setup, p2, 1, **limited, retry_at=clock.rfc3339(later)).status_code == 200
    assert _limit(setup) == (None, None)


def test_the_runners_limit_is_recomputed_and_a_resume_keeps_it(
    setup: Setup, make_client: ClientFactory
) -> None:
    """§6.12: each report recomputes the limit from every placement that should run; a
    resume does not clear a limit with `source: runner`."""
    allow_instances(setup.engine, setup.agent.id, 4)
    first, second, third = placed(setup), placed(setup), placed(setup)
    base = clock.now().replace(microsecond=0)
    soon, later = clock.rfc3339(base + timedelta(hours=1)), clock.rfc3339(base + timedelta(hours=3))
    limited = {"state": "rate_limited", "reason": "quota", "exit_code": 2}
    assert report(setup, first, 1, **limited, retry_at=later).status_code == 200
    assert report(setup, second, 1, **limited, retry_at=soon).status_code == 200
    stopped = setup.owner.patch(
        f"/projects/maintainer/maity/placements/{third['id']}", {"desired": "stopped"}
    )
    assert stopped.status_code == 200, stopped.text
    # The third no longer counts; its report recomputes from the two that should run.
    assert report(setup, third, 1, state="stopped").status_code == 200

    def availability() -> dict[str, Any]:
        found: dict[str, Any] = setup.owner.get(f"{MEMBERS}/{setup.agent.id}").json()[
            "availability"
        ]
        return found

    shown = availability()
    assert (shown["state"], shown["source"], shown["until"]) == ("limited", "runner", soon)
    assert setup.agent.resume().status_code == 200  # another instance resumes
    assert availability()["state"] == "limited"
    assert report(setup, first, 2, state="starting").status_code == 200
    assert availability()["state"] != "limited"
