"""Several worker processes per pod (`MAITY_WORKERS`, hub/context/replicas.md): the setting, the
refusal off PostgreSQL, each process's share of the pool, and one hub serving two processes on
one socket against PostgreSQL. The pieces that must hold across processes are tested between two
hubs in `test_two_processes`; here a request lands on whichever worker accepts it."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from sqlalchemy import Engine, select
from uvicorn.supervisors import multiprocess

from maity_hub import cli, serving
from maity_hub import tables as t
from maity_hub.cli import EXIT_CONFIG, _Server, _WorkerProcess, main
from maity_hub.config import ConfigError, Settings
from maity_hub.mail import outbox
from tests import flow
from tests.test_two_processes import (
    BEFORE_THE_FALLBACK,
    EVENTS,
    Hub,
    _cursor,
    _free_port,
    _listeners,
    _ready,
    _waiting,
    signed_by,
)

PG = "postgresql+psycopg://u:p@localhost/h"


def _settings(**env: str) -> Settings:
    return Settings.from_env({"MAITY_DATABASE_URL": PG, **env})


@pytest.mark.parametrize("value", ["0", "65", "many"])
def test_the_worker_count_is_a_number_from_one_to_sixty_four(value: str) -> None:
    with pytest.raises(ConfigError, match="MAITY_WORKERS"):
        _settings(MAITY_WORKERS=value)
    assert _settings().workers == 1 and _settings(MAITY_WORKERS="4").workers == 4


@pytest.mark.parametrize(
    "url", ["sqlite:///hub.db", "mysql+pymysql://u:p@localhost/h", "mariadb+pymysql://u@h/d"]
)
def test_several_workers_are_refused_off_postgresql(url: str) -> None:
    settings = replace(_settings(), database_url=url, workers=2)
    assert "needs PostgreSQL" in (serving.refusal(settings) or "")
    assert serving.refusal(replace(settings, workers=1)) is None
    assert serving.refusal(replace(_settings(), workers=2)) is None


def test_each_worker_holds_its_share_of_the_pool() -> None:
    settings = _settings(MAITY_WORKERS="4", MAITY_DB_POOL_SIZE="16", MAITY_DB_MAX_OVERFLOW="6")
    share = serving.per_worker(settings)
    assert (share.db_pool_size, share.db_max_overflow) == (4, 1)  # never more than the total
    alone = replace(settings, workers=1)
    assert serving.per_worker(alone) is alone


@pytest.mark.parametrize(
    ("workers", "pool", "refused"), [(8, 16, False), (9, 16, True), (17, 16, True), (2, 3, True)]
)
def test_workers_whose_share_of_the_pool_is_too_small_are_refused(
    workers: int, pool: int, refused: bool
) -> None:
    """The minimum share of two (pmwg, #1276). It dates from when a shared count took a second
    connection from the request's pool; the counts have their own engine since #1320."""
    settings = replace(_settings(), workers=workers, db_pool_size=pool)
    reason = serving.refusal(settings) or ""
    assert (f"needs MAITY_DB_POOL_SIZE of at least {2 * workers}" in reason) is refused


def test_a_worker_that_cannot_build_its_app_stops_the_supervisor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """uvicorn starts a worker that exits otherwise again and again (pmwg, #1276)."""
    from uvicorn.config import STARTUP_FAILURE

    monkeypatch.setenv("MAITY_DATABASE_URL", PG)
    monkeypatch.setenv("MAITY_WEB_DIR", str(tmp_path / "missing"))
    with pytest.raises(SystemExit) as stopped:
        serving.app()
    assert stopped.value.code == STARTUP_FAILURE


def test_a_missing_dashboard_stops_several_workers_before_any_starts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MAITY_DATABASE_URL", PG)
    monkeypatch.setenv("MAITY_WORKERS", "2")
    monkeypatch.setenv("MAITY_WEB_DIR", str(tmp_path / "missing"))
    started: list[Any] = []
    monkeypatch.setattr(multiprocess.Multiprocess, "run", lambda self: started.append(self))
    assert main(["serve"]) == EXIT_CONFIG
    assert "is not a directory" in capsys.readouterr().err and not started


def test_serve_with_several_workers_on_sqlite_stops_in_one_line(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ("MAITY_DATABASE_URL", "MAITY_BIND", "MAITY_PUBLIC_URL", "MAITY_WEB_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MAITY_WORKERS", "2")
    assert main(["serve"]) == EXIT_CONFIG
    assert "MAITY_WORKERS=2 needs PostgreSQL" in capsys.readouterr().err


def test_a_worker_serves_with_the_hubs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """uvicorn's worker builds its server in the child; ours releases the long-polls on the stop
    signal (`_Server.handle_exit`). The supervisor reaches the class by this module name."""
    assert isinstance(getattr(multiprocess, "Process", None), type)
    worker = _WorkerProcess.__new__(_WorkerProcess)
    worker.config = cli._config(_settings(), "maity_hub.serving:app", 2)
    worker._server = None
    assert type(worker.server) is _Server
    assert worker.config.factory is True and worker.config.workers == 2


# --- one hub, two processes, PostgreSQL -------------------------------------------------------


@pytest.fixture
def hub(database_url: str, migrated: Engine, tmp_path: Path) -> Iterator[Hub]:
    if not database_url.startswith("postgresql"):
        pytest.skip("only PostgreSQL runs several workers")
    port = _free_port()
    log = tmp_path / "hub.log"
    env = {
        **os.environ,
        "MAITY_DATABASE_URL": migrated.url.render_as_string(hide_password=False),
        "MAITY_BIND": f"127.0.0.1:{port}",
        "MAITY_PUBLIC_URL": f"http://127.0.0.1:{port}",
        "MAITY_ALLOW_PLAIN_HTTP": "1",
        "MAITY_WEB_DIR": "",
        "MAITY_WORKERS": "2",
    }
    with log.open("wb") as out:
        process = subprocess.Popen(
            [sys.executable, "-m", "maity_hub", "serve"], env=env, stdout=out, stderr=out
        )
    served = Hub(f"http://127.0.0.1:{port}", process, log)
    try:
        deadline = time.monotonic() + 60
        _ready(served, deadline)
        while time.monotonic() < deadline:  # both workers listening
            if _listeners(migrated) >= 2:
                break
            time.sleep(0.1)
        else:
            pytest.fail(f"the two workers' listeners did not connect:\n{log.read_text()[-2000:]}")
        yield served
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@pytest.fixture
def team(hub: Hub, migrated: Engine) -> tuple[flow.Human, flow.Agent, flow.Agent]:
    def client() -> Any:
        return httpx.Client(base_url=hub.url, timeout=40)

    owner = flow.human(client, migrated)
    flow.project(owner)
    return owner, flow.agent(client, owner), flow.agent(client, owner)


@pytest.fixture
def agents(team: tuple[flow.Human, flow.Agent, flow.Agent]) -> tuple[flow.Agent, flow.Agent]:
    return team[1], team[2]


def test_two_workers_are_two_processes_of_one_hub(hub: Hub, migrated: Engine) -> None:
    with migrated.connect() as conn:
        pods = conn.execute(select(t.hub_pod.c.pod)).scalars().all()
    assert len(set(pods)) == 2, pods
    assert "maity-hub: 2 workers" in hub.log.read_text()


def test_every_wait_wakes_whichever_worker_wrote(
    hub: Hub, agents: tuple[flow.Agent, flow.Agent]
) -> None:
    """Each request lands on either worker: a wake-up that did not cross between the two would
    end its wait only at the fallback read. Every one of the rounds must end before it, bar one a
    loaded runner may answer late."""
    writer, waiter = agents
    late = 0
    for attempt in range(8):
        cursor = _cursor(hub, waiter)
        begun = time.monotonic()
        thread, answers = _waiting(hub, waiter, cursor, 25)
        time.sleep(0.4)
        said = hub.post(
            writer,
            EVENTS,
            {"kind": "message", "type": "notice", "to": waiter.id, "body": f"{attempt}"},
        )
        assert said.status_code in (200, 201), said.text
        thread.join(timeout=30)
        assert answers and [e["kind"] for e in answers[0].json()["items"]] == ["message"]
        late += time.monotonic() - begun >= BEFORE_THE_FALLBACK
    assert late <= 1, late


def test_a_nonce_counts_once_over_both_workers(
    hub: Hub, agents: tuple[flow.Agent, flow.Agent]
) -> None:
    _, agent = agents
    for _ in range(6):
        headers = signed_by(agent, "GET", "/api/v1/me")
        assert hub.send(headers, "GET", "/api/v1/me").status_code == 200
        again = hub.send(headers, "GET", "/api/v1/me")
        assert again.status_code == 401 and again.headers["Maity-Error"] == "nonce_reused"


def test_a_newer_wait_supersedes_the_older_whatever_worker_holds_it(
    hub: Hub, agents: tuple[flow.Agent, flow.Agent]
) -> None:
    _, waiter = agents
    for _ in range(4):
        cursor = _cursor(hub, waiter)
        thread, first = _waiting(hub, waiter, cursor, 8)
        time.sleep(1)
        newer, second = _waiting(hub, waiter, cursor, 1)
        thread.join(timeout=30)
        newer.join(timeout=30)
        assert first and first[0].json()["superseded"] is True
        assert second and second[0].json()["superseded"] is False


def test_the_stop_signal_releases_the_waits_of_every_worker(
    hub: Hub, agents: tuple[flow.Agent, flow.Agent]
) -> None:
    writer, waiter = agents
    waits = [_waiting(hub, agent, _cursor(hub, agent), 50) for agent in (writer, waiter)]
    time.sleep(1)
    begun = time.monotonic()
    hub.process.send_signal(signal.SIGTERM)
    for thread, answers in waits:
        thread.join(timeout=30)
        assert answers and answers[0].status_code == 200
    hub.process.wait(timeout=30)
    assert time.monotonic() - begun < 15  # not the 50 seconds the waits asked for


def test_an_isolation_ends_the_agents_wait_on_every_worker(
    hub: Hub, team: tuple[flow.Human, flow.Agent, flow.Agent]
) -> None:
    """The worker that isolates ends the waits it holds; a wait held by another worker ends at
    its next read (e5kk, #1276). Repeated, so that some isolation lands on the other worker."""
    owner, _, waiter = team
    for _ in range(4):
        thread, answers = _waiting(hub, waiter, _cursor(hub, waiter), 40)
        time.sleep(0.5)
        begun = time.monotonic()
        isolated = owner.post(
            f"/projects/maintainer/maity/members/{waiter.id}/isolate", {"reason": "a test"}
        )
        assert isolated.status_code == 200, isolated.text
        thread.join(timeout=30)
        assert answers and answers[0].json()["items"] == []
        assert time.monotonic() - begun < BEFORE_THE_FALLBACK + 1.5
        lifted = owner.delete(f"/projects/maintainer/maity/members/{waiter.id}/isolate")
        assert lifted.status_code in (200, 204), lifted.text


def test_a_workers_pass_runs_once_per_interval_over_both_workers(
    hub: Hub, migrated: Engine
) -> None:
    """The mail worker in each process, claimed once per interval across the pod (dzse,
    #1276)."""
    from tests.test_two_processes import passes_of_the_mail_worker

    gaps = passes_of_the_mail_worker(migrated)
    assert len(gaps) >= 1 and min(gaps) >= outbox.INTERVAL, gaps


# --- several pods (`MAITY_REPLICAS`) -----------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "101", "many"])
def test_the_replica_count_is_a_number_from_one_to_a_hundred(value: str) -> None:
    with pytest.raises(ConfigError, match="MAITY_REPLICAS"):
        _settings(MAITY_REPLICAS=value)
    assert _settings().replicas == 1 and _settings(MAITY_REPLICAS="3").replicas == 3


def test_several_replicas_are_refused_off_postgresql() -> None:
    settings = replace(_settings(), database_url="sqlite:///hub.db", replicas=2)
    assert "MAITY_REPLICAS=2 needs PostgreSQL" in (serving.refusal(settings) or "")


def test_several_replicas_are_refused_with_a_local_attachment_directory(tmp_path: Path) -> None:
    """Each pod's directory holds only the files it took; the single-server setup keeps it."""
    local = replace(_settings(), attachment_dir=tmp_path, replicas=2)
    assert "local attachment directory" in (serving.refusal(local) or "")
    assert serving.refusal(replace(local, replicas=1)) is None
    assert serving.refusal(replace(local, attachment_dir=None)) is None  # attachments off
    assert serving.refusal(replace(local, attachment_store="s3")) is None


def test_the_connection_budget_counts_every_pod_and_process() -> None:
    settings = _settings(
        MAITY_REPLICAS="3", MAITY_WORKERS="2", MAITY_DB_POOL_SIZE="10", MAITY_DB_MAX_OVERFLOW="5"
    )
    # 3 pods and the surge pod; per pod 2 × (5 + 2 + 2 shared + 1 listener) + 1 health.
    assert serving.connections(settings) == 4 * (2 * (5 + 2 + 2 + 1) + 1)
    assert serving.budget_warning(settings, 100, 3) is None
    warning = serving.budget_warning(settings, 50, 3) or ""
    assert "84 database connections" in warning and "takes 47" in warning
    assert "overflow 2 + 2 shared + 1 listener" in warning  # the text adds up to the number
    assert (
        serving.connections(_settings()) == 16 + 16 + 2 + 1 + 1
    )  # the single-server hub, no surge


@pytest.mark.parametrize(
    ("replicas", "workers", "pool", "overflow"),
    [(1, 1, 16, 16), (2, 4, 16, 6), (5, 8, 17, 3), (3, 3, 7, 0)],
)
def test_the_budget_is_what_the_workers_hold(
    replicas: int, workers: int, pool: int, overflow: int
) -> None:
    """Pinned to `per_worker`: whatever a worker is given is what the budget counts (pmwg,
    #1278)."""
    settings = replace(
        _settings(), replicas=replicas, workers=workers, db_pool_size=pool, db_max_overflow=overflow
    )
    share = serving.per_worker(settings)
    held = workers * (share.db_pool_size + share.db_max_overflow + 2 + 1) + 1
    assert serving.connections(settings) == serving.pods_at_most(settings) * held
    assert serving.pods_at_most(settings) == replicas + (replicas > 1)


def test_a_budget_past_the_servers_limit_is_said_at_the_start(
    migrated: Engine, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    from maity_hub.app import warn_on_connection_budget

    if not database_url.startswith("postgresql"):
        warn_on_connection_budget(migrated, replace(_settings(), replicas=100))
        assert not caplog.records  # only PostgreSQL has the limit to read
        return
    with caplog.at_level("WARNING"):
        warn_on_connection_budget(migrated, _settings())
        assert not caplog.records
        warn_on_connection_budget(migrated, _settings(MAITY_REPLICAS="100"))
    assert any("database connections" in r.getMessage() for r in caplog.records)
