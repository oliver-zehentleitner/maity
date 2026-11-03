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
    assert (share.db_pool_size, share.db_max_overflow) == (4, 1)
    tiny = serving.per_worker(replace(settings, db_pool_size=2, db_max_overflow=0))
    assert (tiny.db_pool_size, tiny.db_max_overflow) == (1, 0)  # never an empty pool
    alone = replace(settings, workers=1)
    assert serving.per_worker(alone) is alone


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
def agents(hub: Hub, migrated: Engine) -> tuple[flow.Agent, flow.Agent]:
    def client() -> Any:
        return httpx.Client(base_url=hub.url, timeout=40)

    owner = flow.human(client, migrated)
    flow.project(owner)
    return flow.agent(client, owner), flow.agent(client, owner)


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
