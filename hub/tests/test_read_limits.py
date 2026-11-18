"""docs/api.md §1.7 "Reads per credential", §16.5 `max_reads_per_minute`: a signed-in caller's
reads of the API are counted per credential in the process and refused past the limit, before
any side effect of §2.4 (tsk-ybc2ma72dzvq, item 7)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, read_limits
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.routes import events as events_route
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import listening
from tests.test_runners import call, paired

API = "/api/v1"
PROJECT = "/projects/maintainer/maity"
LOW = 60  # the lowest value the setting takes, so a test reaches it quickly
# A window's start, after the process started: a signed call's timestamp is refused before
# that (auth/caller.py `PROCESS_STARTED`), and the hub's clock is what the window counts in.
BASE = float((int(time.time()) // 60 + 2) * 60)


class Moment:
    """The hub's clock, at `BASE` plus the seconds a test moves it to."""

    def __init__(self) -> None:
        self.at = BASE

    def __call__(self) -> datetime:
        return datetime.fromtimestamp(self.at, UTC)

    def to(self, seconds: float) -> None:
        self.at = BASE + seconds


@pytest.fixture
def moment() -> Moment:
    found = Moment()
    clock.set_source(found)  # conftest resets the clock after each test
    return found


@pytest.fixture
def owner(moment: Moment, make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(lambda **kw: make_client(max_reads_per_minute=LOW, **kw), migrated)
    flow.project(human)
    return human


def _project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def _bearer(agent: factory.Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent.value}"}


def _get(client: Any, agent: factory.Agent, path: str = "/me", **headers: str) -> Any:
    return client.get(f"{API}{path}", headers=_bearer(agent) | headers)


def _reads(client: Any, agent: factory.Agent, count: int, path: str = "/me") -> None:
    for n in range(count):
        got = _get(client, agent, path)
        assert got.status_code == 200, (n, got.text)


def _refused(response: Any) -> int:
    assert response.status_code == 429, response.text
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["Maity-Error"] == "rate_limited"
    return int(response.headers["Retry-After"])


def _count(key: str) -> int:
    found = read_limits.COUNTER._counts.get(key)
    return 0 if found is None else found.current


@pytest.fixture
def agent(owner: flow.Human, migrated: Engine) -> factory.Agent:
    return factory.agent(migrated, _project_id(migrated), owner.id)


@pytest.fixture
def client(make_client: ClientFactory) -> Any:
    return make_client(max_reads_per_minute=LOW)


# --- the limit and its window -------------------------------------------------------------


def test_reads_under_the_limit_pass_and_the_next_is_rate_limited(
    moment: Moment, agent: factory.Agent, client: Any
) -> None:
    moment.to(30)
    _reads(client, agent, LOW)
    refused = _get(client, agent)
    # Retry-After: the seconds until one more fits; this window's 60 become the next window's
    # previous ones and fit once 1/60 of it has passed: 30 s here, then 1 s, rounded up (a
    # float's last digit may add a second, never take one).
    assert _refused(refused) in (31, 32)
    assert refused.json()["error"]["message"] == "too many reads for this credential"


def test_the_window_slides_across_its_edges_and_the_count_recovers(
    moment: Moment, agent: factory.Agent, client: Any
) -> None:
    moment.to(30)
    _reads(client, agent, LOW)
    _refused(_get(client, agent))
    moment.to(59.5)  # the end of the window: still none
    _refused(_get(client, agent))
    moment.to(60.5)  # the next window: the previous 60 still weigh almost all of it
    assert _refused(_get(client, agent)) == 1
    moment.to(61)  # one more fits now, and no more
    assert _get(client, agent).status_code == 200
    _refused(_get(client, agent))
    moment.to(90)  # half of the previous window still counts: 30 of it, and 1 of this one
    _reads(client, agent, LOW - 30 - 1)
    _refused(_get(client, agent))
    moment.to(180)  # two windows on, nothing counts any more
    _reads(client, agent, LOW)
    _refused(_get(client, agent))


def test_the_limit_is_per_credential(
    moment: Moment, owner: flow.Human, agent: factory.Agent, client: Any, migrated: Engine
) -> None:
    other = factory.agent(migrated, _project_id(migrated), owner.id, instance="wk2e")
    _reads(client, agent, LOW)
    _refused(_get(client, agent))
    _reads(client, other, 5)  # another credential, the same client address
    assert owner.get("/me").status_code == 200  # and a human's session


def test_a_refused_read_writes_nothing(
    moment: Moment, owner: flow.Human, agent: factory.Agent, client: Any, migrated: Engine
) -> None:
    moment.to(1)
    card = factory.card(
        migrated,
        _project_id(migrated),
        agent.membership_id,
        claim_holder=agent.membership_id,
        claim_instance=agent.instance,
        lease_until=clock.now() + timedelta(minutes=5),
    )
    old = clock.now() - timedelta(hours=1)

    def age() -> None:
        with migrated.begin() as conn:
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == agent.credential_id)
                .values(last_used_at=old)
            )
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == agent.membership_id)
                .values(last_seen_at=old)
            )
            conn.execute(
                update(t.agent_session)
                .where(t.agent_session.c.id == agent.session_id)
                .values(last_seen_at=old)
            )
            conn.execute(update(t.card).where(t.card.c.id == card).values(lease_until=old))

    def written() -> tuple[Any, ...]:
        with migrated.connect() as conn:
            return (
                conn.execute(
                    select(t.credential.c.last_used_at).where(
                        t.credential.c.id == agent.credential_id
                    )
                ).scalar(),
                conn.execute(
                    select(t.membership.c.last_seen_at).where(
                        t.membership.c.id == agent.membership_id
                    )
                ).scalar(),
                conn.execute(
                    select(t.agent_session.c.last_seen_at).where(
                        t.agent_session.c.id == agent.session_id
                    )
                ).scalar(),
                conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card)).scalar(),
            )

    _reads(client, agent, LOW - 1)
    age()
    _reads(client, agent, 1)  # the last read that fits writes all four
    assert all(value != old for value in written()), written()
    age()
    _refused(_get(client, agent))
    assert written() == (old, old, old, old)  # no last use, presence, session or lease


def test_a_transaction_run_again_counts_its_request_once() -> None:
    counter = read_limits.ReadCounter()
    request, other = object(), object()
    assert counter.take("crd-a", 2, request, 10.0) == 0
    assert counter.take("crd-a", 2, request, 10.1) == 0  # the same request, run again
    assert counter._counts["crd-a"].current == 1
    assert counter.take("crd-a", 2, other, 10.2) == 0
    assert counter.take("crd-a", 2, object(), 10.3) > 0


def test_credentials_not_read_for_two_windows_are_forgotten() -> None:
    counter = read_limits.ReadCounter()
    for n in range(20):
        counter.take(f"crd-{n}", 10, object(), 1.0)  # window 0
    counter.take("crd-0", 10, object(), 61.0)  # window 1: none of window 0 is stale yet
    assert len(counter) == 20
    counter.take("crd-0", 10, object(), 125.0)  # window 2: window 0 is, 8 of it go per call
    assert len(counter) == 20 - read_limits.FORGET_PER_CALL
    for _ in range(2):
        counter.take("crd-new", 1000, object(), 130.0)
    assert set(counter._counts) == {"crd-0", "crd-new"}  # crd-0 still reaches window 2


def test_concurrent_reads_are_counted_exactly() -> None:
    counter = read_limits.ReadCounter()

    def reads() -> None:
        for _ in range(500):
            counter.take("crd-a", 100000, object(), 5.0)

    threads = [threading.Thread(target=reads) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert counter._counts["crd-a"].current == 4000


# --- what counts --------------------------------------------------------------------------


def test_writes_are_not_counted(moment: Moment, agent: factory.Agent, client: Any) -> None:
    _reads(client, agent, LOW)
    _refused(_get(client, agent))
    resumed = client.post(f"{API}/me/resume", json={"client": "test"}, headers=_bearer(agent))
    assert resumed.status_code < 300, resumed.text
    assert _count(agent.credential_id) == LOW


def test_a_bridges_reads_count_against_its_own_credential(
    moment: Moment, owner: flow.Human, client: Any, migrated: Engine
) -> None:
    project_id = _project_id(migrated)
    served = factory.agent(migrated, project_id, owner.id, "coder", instance="wk2e")
    bridge = factory.agent(migrated, project_id, owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    for _ in range(LOW):
        got = _get(client, bridge, f"{PROJECT}/tasks", **{"Maity-For": served.agent_id})
        assert got.status_code == 200, got.text
    assert (_count(bridge.credential_id), _count(served.credential_id)) == (LOW, 0)
    _refused(_get(client, bridge, f"{PROJECT}/tasks", **{"Maity-For": served.agent_id}))
    _refused(_get(client, bridge, f"{PROJECT}/tasks"))  # its own reads share the count
    assert _get(client, served, f"{PROJECT}/tasks").status_code == 200  # not the served agent's


def test_a_runners_reads_count_and_a_refused_one_writes_nothing(
    moment: Moment, owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    runner = paired(make_client, owner)
    client = make_client(max_reads_per_minute=LOW)
    for _ in range(LOW):
        got = call(client, runner, "GET", f"{API}/runner/placements")
        assert got.status_code == 200, got.text
    with migrated.begin() as conn:
        old = clock.now() - timedelta(hours=1)
        conn.execute(
            update(t.runner_credential)
            .where(t.runner_credential.c.id == runner.credential_id)
            .values(last_used_at=old)
        )
        conn.execute(update(t.runner).where(t.runner.c.id == runner.id).values(last_seen_at=old))
    _refused(call(client, runner, "GET", f"{API}/runner/placements"))
    with migrated.connect() as conn:
        used = conn.execute(
            select(t.runner_credential.c.last_used_at).where(
                t.runner_credential.c.id == runner.credential_id
            )
        ).scalar()
        seen = conn.execute(select(t.runner.c.last_seen_at).where(t.runner.c.id == runner.id))
        assert (used, seen.scalar()) == (old, old)


def test_unlimited_counts_nothing(
    moment: Moment, owner: flow.Human, migrated: Engine, make_client: ClientFactory
) -> None:
    agent = factory.agent(migrated, _project_id(migrated), owner.id)
    client = make_client(max_reads_per_minute="unlimited")
    _reads(client, agent, LOW + 10)
    assert _count(agent.credential_id) == 0


def test_bootstrap_counts_once_and_a_refusal_answers_the_whole_request(
    moment: Moment, agent: factory.Agent, client: Any
) -> None:
    _reads(client, agent, LOW - 1)
    whole = _get(client, agent, "/bootstrap")
    assert whole.status_code == 200 and whole.json()["me"]["status"] == 200, whole.text
    assert _count(agent.credential_id) == LOW  # one read for all its parts
    assert _refused(_get(client, agent, "/bootstrap")) > 0  # with Retry-After, no parts


# --- the long-poll ------------------------------------------------------------------------


def test_a_long_poll_counts_once_however_many_passes_it_makes(
    moment: Moment, agent: factory.Agent, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events_route, "FALLBACK_SECONDS", 0.02)  # about 50 passes in 1 s
    passes: list[str] = []
    began = time.monotonic()
    with listening(client.app.state.engine, lambda *a: passes.append(a[2])):
        held = _get(client, agent, f"{PROJECT}/events?after=999999&wait=1")
    assert held.status_code == 200, held.text
    assert time.monotonic() - began >= 0.9 and len(passes) > 10  # held, read again and again
    assert _count(agent.credential_id) == 1


@pytest.mark.parametrize("busy", [False, True])
def test_a_maity_wait_loop_at_its_cadence_never_meets_the_limit(
    moment: Moment,
    owner: flow.Human,
    agent: factory.Agent,
    make_client: ClientFactory,
    monkeypatch: pytest.MonkeyPatch,
    busy: bool,
) -> None:
    # `maity wait` (cli.py `cmd_wait`): one long-poll of up to 55 s at a time (LONG_POLL),
    # armed again as soon as it answers, and the unread-chats read when its --timeout (600 s
    # by default) ends. Quiet, a poll is held to its end, at the lowest setting, 60; busy,
    # every poll answers at once with events and is armed again a second later, at the
    # default, 1000.
    monkeypatch.setattr(events_route, "FALLBACK_SECONDS", 0.05)
    client = make_client() if busy else make_client(max_reads_per_minute=LOW)
    sent = owner.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": agent.agent_id, "body": "for you"},
    )
    assert sent.status_code == 201, sent.text
    at, polls = 0.0, 0
    while at < (180 if busy else 660):
        moment.to(at)
        if busy:
            got = _get(client, agent, f"{PROJECT}/events?after=0&wait=55")
            assert got.json()["items"], got.text  # answered at once
            at += 1.0
        else:
            got = _get(client, agent, f"{PROJECT}/events?after=999999&wait=1")  # held
            at += 55.0
        assert got.status_code == 200, (at, got.text)
        polls += 1
        if not busy and polls % 11 == 0:  # the timeout's unread-chats read, every ~600 s
            note = _get(client, agent, f"{PROJECT}/conversations?renew=false")
            assert note.status_code == 200, note.text
    assert polls >= (180 if busy else 12)


# --- the human's session ------------------------------------------------------------------


def _session_updates(engine: Engine, call: Any) -> tuple[Any, list[str]]:
    sent: list[str] = []

    def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        if statement.lstrip().upper().startswith("UPDATE"):
            sent.append(statement.split()[1])

    with listening(engine, heard):
        response = call()
    return response, sent


def _presence_due(engine: Engine, human_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.human_id == human_id)
            .values(last_seen_at=clock.now() - timedelta(minutes=5))
        )


@pytest.mark.parametrize("ended", ["revoked", "expired", "deleted_account"])
def test_an_ended_session_writes_no_presence(
    moment: Moment, owner: flow.Human, migrated: Engine, ended: str
) -> None:
    _presence_due(migrated, owner.id)
    with migrated.begin() as conn:
        if ended == "revoked":
            conn.execute(
                update(t.human_session)
                .where(t.human_session.c.human_id == owner.id)
                .values(ended_at=clock.now())
            )
        elif ended == "expired":
            conn.execute(
                update(t.human_session)
                .where(t.human_session.c.human_id == owner.id)
                .values(expires_at=clock.now() - timedelta(seconds=1))
            )
        else:
            conn.execute(
                update(t.human).where(t.human.c.id == owner.id).values(deleted_at=clock.now())
            )
    response, sent = _session_updates(migrated, lambda: owner.get("/me"))
    assert response.status_code == 401, response.text
    assert sent == []  # not even an update that matches nothing


def test_a_live_session_writes_presence_once_due_and_a_refused_read_none(
    moment: Moment, owner: flow.Human, migrated: Engine
) -> None:
    _presence_due(migrated, owner.id)
    response, sent = _session_updates(migrated, lambda: owner.get("/me"))
    assert response.status_code == 200, response.text
    assert sent[:3] == ["human_session", "human", "membership"]
    response, sent = _session_updates(migrated, lambda: owner.get("/me"))
    assert response.status_code == 200 and sent == []  # within the minute: nothing at all
    for _ in range(LOW):  # the session's own reads since signing in count too
        if owner.get("/me").status_code == 429:
            break
    _presence_due(migrated, owner.id)
    moment.to(5)
    response, sent = _session_updates(migrated, lambda: owner.get("/me"))
    _refused(response)
    assert sent == []  # no presence of the session, its human or its memberships


def test_a_sessions_reads_count_by_its_hash_and_the_dashboard_gets_retry_after(
    moment: Moment, owner: flow.Human
) -> None:
    answered = [owner.get("/me").status_code for _ in range(LOW)]
    # The sign-in's own read (`GET /auth/session`, flow.human) counted too: the last is refused.
    assert answered == [200] * (LOW - 1) + [429]
    assert _refused(owner.get(f"{PROJECT}/tasks")) > 0
    keys = list(read_limits.COUNTER._counts)
    assert len(keys) == 1 and len(keys[0]) == 64  # the session's hash, never the cookie


# --- the instance's value -----------------------------------------------------------------


def _admin(make_client: ClientFactory, migrated: Engine, owner: flow.Human) -> flow.Human:
    """The owner, the earliest account and so the instance admin, on an app whose environment
    leaves `max_reads_per_minute` to the admin."""
    client = make_client()
    signed_in = factory.login(client, owner.id, engine=migrated)
    assert signed_in.status_code == 200, signed_in.text
    csrf = client.get(f"{API}/auth/session").json()["csrf_token"]
    return flow.Human(client, csrf, owner.id)


def test_the_value_is_kept_30_seconds_and_a_patch_drops_it_at_once(
    moment: Moment, owner: flow.Human, migrated: Engine, make_client: ClientFactory
) -> None:
    agent = factory.agent(migrated, _project_id(migrated), owner.id)
    admin = _admin(make_client, migrated, owner)
    client = make_client()  # the default, 1000
    moment.to(1)
    _reads(client, agent, 1)
    with migrated.begin() as conn:  # an admin's value written behind this process's back
        store.put(conn, "limits.max_reads_per_minute", LOW, None)
    moment.to(2)
    _reads(client, agent, LOW + 10)  # the kept value, 1000, still applies
    moment.to(32)
    _refused(_get(client, agent))  # read again after 30 s
    with migrated.begin() as conn:
        store.put(conn, "limits.max_reads_per_minute", None, None)
    read_limits.forget_instance_value()
    moment.to(33)
    _reads(client, agent, 1)  # 1000 again
    set_low = admin.patch("/admin/settings/limits", {"max_reads_per_minute": LOW})
    assert set_low.status_code == 200, set_low.text
    assert set_low.json()["max_reads_per_minute"] == {"value": LOW, "source": "admin"}
    _refused(_get(client, agent))  # at once, not after 30 s


def test_a_kept_value_costs_no_statement(
    moment: Moment, owner: flow.Human, migrated: Engine, make_client: ClientFactory
) -> None:
    agent = factory.agent(migrated, _project_id(migrated), owner.id)
    kept, env = make_client(), make_client(max_reads_per_minute=1000)

    def statements(client: Any) -> int:
        sent: list[str] = []
        with listening(migrated, lambda *a: sent.append(a[2])):
            assert _get(client, agent).status_code == 200
        return len(sent)

    _reads(kept, agent, 1)  # reads the value once
    assert statements(kept) == statements(env)  # then no more than the environment's


def test_the_setting_takes_60_to_100000_or_unlimited(
    owner: flow.Human, migrated: Engine, make_client: ClientFactory
) -> None:
    admin = _admin(make_client, migrated, owner)
    for bad in (59, 100001, True, "many", 1.5):
        got = admin.patch("/admin/settings/limits", {"max_reads_per_minute": bad})
        assert got.status_code == 400, (bad, got.text)
    got = admin.patch("/admin/settings/limits", {"max_reads_per_minute": "unlimited"})
    assert got.json()["max_reads_per_minute"] == {"value": "unlimited", "source": "admin"}
    back = admin.patch("/admin/settings/limits", {"max_reads_per_minute": None})
    assert back.json()["max_reads_per_minute"] == {"value": 1000, "source": "default"}


def test_the_environment_sets_it_and_wins(owner: flow.Human) -> None:
    got = owner.get("/admin/settings/limits").json()  # the owner's app has LOW from MAITY_…
    assert got["max_reads_per_minute"] == {"value": LOW, "source": "env"}
    refused = owner.patch("/admin/settings/limits", {"max_reads_per_minute": 100})
    assert refused.json()["error"]["details"]["fields"] == {
        "max_reads_per_minute": "set_by_environment"
    }
    for value, parsed in (("60", 60), ("100000", 100000), ("unlimited", "unlimited"), ("", None)):
        env = {"MAITY_MAX_READS_PER_MINUTE": value}
        assert Settings.from_env(env).max_reads_per_minute == parsed
    for bad in ("59", "100001", "many", "-1"):
        with pytest.raises(ConfigError, match="MAITY_MAX_READS_PER_MINUTE"):
            Settings.from_env({"MAITY_MAX_READS_PER_MINUTE": bad})


# --- the refusal's log line ---------------------------------------------------------------


def test_one_log_line_per_refusal_with_the_route_and_a_tag_only(
    moment: Moment,
    agent: factory.Agent,
    owner: flow.Human,
    client: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="maity_hub.read_limits")
    _reads(client, agent, LOW, f"{PROJECT}/tasks")
    assert [r for r in caplog.records if r.name == "maity_hub.read_limits"] == []
    _refused(_get(client, agent, f"{PROJECT}/tasks"))
    _refused(_get(client, agent))
    lines = [r.getMessage() for r in caplog.records if r.name == "maity_hub.read_limits"]
    assert len(lines) == 2, lines
    tag = read_limits.tag(agent.credential_id)
    assert len(tag) == 12
    assert lines[0] == (
        f"read limit: GET /api/v1/projects/{{owner}}/{{slug}}/tasks credential={tag} "
        f"limit={LOW} retry_after={lines[0].rsplit('=', 1)[1]}"
    )
    assert f"GET /api/v1/me credential={tag} " in lines[1]
    secret = agent.value.split(".")[2]
    for line in lines:
        for raw in (agent.credential_id, agent.value, secret, agent.agent_id, "maintainer"):
            assert raw not in line
    # A session's tag hides its hash and its cookie the same way.
    for _ in range(LOW):
        if owner.get("/me").status_code == 429:
            break
    cookie = owner.client.cookies.get("maity_session")
    [line] = [
        r.getMessage()
        for r in caplog.records
        if r.name == "maity_hub.read_limits" and r.getMessage() not in lines
    ]
    assert cookie and cookie not in line and owner.id not in line
    assert all(key not in line for key in read_limits.COUNTER._counts)  # nor the session's hash


def test_the_tag_is_keyed_by_the_instance_key_when_there_is_one() -> None:
    read_limits.configure(b"k" * 32)
    first = read_limits.tag("crd-a")
    read_limits.configure(b"k" * 32)
    assert read_limits.tag("crd-a") == first  # the same across processes with the key
    read_limits.configure(None)
    assert read_limits.tag("crd-a") != first  # a process's own random key without one
