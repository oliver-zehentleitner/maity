"""Two real hub processes on one PostgreSQL: what must hold across replicas, seen from the outside
(hub/context/replicas.md). The unit tests of each piece run in one process and stand in for the
other one; here nothing is stood in for. `hub-postgresql` runs this file, every other database
skips it: only PostgreSQL runs replicas."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2 as httpx
import pytest
from sqlalchemy import Engine, text

from maity_hub.db import APPLICATION_LISTENER
from tests import flow
from tests.test_auth_agent import signed

EVENTS = "/api/v1/projects/maintainer/maity/events"
# A wait reads again after 2 seconds anyway (`wakeups.FALLBACK_SECONDS`). Answered sooner, counted
# from before the wait was sent, only a wake-up can have ended it.
BEFORE_THE_FALLBACK = 1.9


@dataclass
class Hub:
    url: str
    process: subprocess.Popen[bytes]
    log: Path

    def call(
        self, agent: flow.Agent, method: str, path: str, query: str = "", **kwargs: Any
    ) -> httpx.Response:
        return self.send(signed_by(agent, method, path, query), method, path, query, **kwargs)

    def post(self, agent: flow.Agent, path: str, body: dict[str, Any]) -> httpx.Response:
        raw = json.dumps(body).encode()
        headers = signed_by(agent, "POST", path, "", raw) | agent.key()
        headers["Content-Type"] = "application/json"
        return self.send(headers, "POST", path, content=raw)

    def send(
        self, headers: dict[str, str], method: str, path: str, query: str = "", **kwargs: Any
    ) -> httpx.Response:
        url = f"{self.url}{path}" + (f"?{query}" if query else "")
        return httpx.request(method, url, headers=headers, timeout=40, **kwargs)


def signed_by(
    agent: flow.Agent, method: str, path: str, query: str = "", body: bytes = b""
) -> dict[str, str]:
    who = SimpleNamespace(value=agent.credential, credential_id=agent.credential_id)
    return signed(who, method, path, query, body)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _start(database_url: str, tmp_path: Path, name: str) -> Hub:
    port = _free_port()
    log = tmp_path / f"hub-{name}.log"
    env = {
        **os.environ,
        "MAITY_DATABASE_URL": database_url,
        "MAITY_BIND": f"127.0.0.1:{port}",
        "MAITY_PUBLIC_URL": f"http://127.0.0.1:{port}",
        "MAITY_ALLOW_PLAIN_HTTP": "1",
        "MAITY_WEB_DIR": "",
    }
    with log.open("wb") as out:
        process = subprocess.Popen(
            [sys.executable, "-m", "maity_hub", "serve"], env=env, stdout=out, stderr=out
        )
    return Hub(f"http://127.0.0.1:{port}", process, log)


def _ready(hub: Hub, deadline: float) -> None:
    while time.monotonic() < deadline:
        if hub.process.poll() is not None:
            break
        try:
            if httpx.get(f"{hub.url}/api/v1/health", timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.fail(f"{hub.url} did not come up:\n{hub.log.read_text()[-2000:]}")


@pytest.fixture(autouse=True)
def _only_on_postgresql(database_url: str) -> None:
    """Before anything is set up: only PostgreSQL runs replicas."""
    if not database_url.startswith("postgresql"):
        pytest.skip("only PostgreSQL runs replicas")


@pytest.fixture
def hubs(migrated: Engine, tmp_path: Path) -> Iterator[tuple[Hub, Hub]]:
    url = migrated.url.render_as_string(hide_password=False)
    pair = (_start(url, tmp_path, "a"), _start(url, tmp_path, "b"))
    try:
        deadline = time.monotonic() + 60
        for hub in pair:
            _ready(hub, deadline)
        while time.monotonic() < deadline:  # a wake-up needs both listeners in place
            if _listeners(migrated) >= 2:
                break
            time.sleep(0.1)
        else:
            pytest.fail("the two hubs' listeners did not connect")
        yield pair
    finally:
        for hub in pair:
            hub.process.terminate()
        for hub in pair:
            try:
                hub.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                hub.process.kill()
                hub.process.wait()


@pytest.fixture
def agents(hubs: tuple[Hub, Hub], migrated: Engine) -> tuple[flow.Agent, flow.Agent]:
    """Set up over HTTP too: a test client's app would be a third replica with its own listener."""

    def client() -> Any:  # as much of a test client as `flow` uses
        return httpx.Client(base_url=hubs[0].url, timeout=40)

    owner = flow.human(client, migrated)
    flow.project(owner)
    return flow.agent(client, owner), flow.agent(client, owner)


def _waiting(
    hub: Hub, agent: flow.Agent, cursor: str, seconds: int
) -> tuple[threading.Thread, list[httpx.Response]]:
    answers: list[httpx.Response] = []

    def wait() -> None:
        answers.append(hub.call(agent, "GET", EVENTS, f"after={cursor}&wait={seconds}"))

    thread = threading.Thread(target=wait)
    thread.start()
    return thread, answers


def _listeners(engine: Engine) -> int:
    with engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE application_name = :name AND datname = current_database() "
                "AND state = 'idle' AND query ILIKE 'LISTEN %'"  # connected is not listening yet
            ),
            {"name": APPLICATION_LISTENER},
        ).scalar_one()
    return int(count)


def _cursor(hub: Hub, agent: flow.Agent) -> str:
    answer = hub.call(agent, "GET", EVENTS, "after=latest")
    assert answer.status_code == 200, answer.text
    return str(answer.json()["cursor"])


def test_a_wait_on_one_process_wakes_from_a_write_on_the_other(
    hubs: tuple[Hub, Hub], agents: tuple[flow.Agent, flow.Agent]
) -> None:
    (a, b), (writer, waiter) = hubs, agents
    took: list[float] = []
    # Tried a few times since a loaded runner may answer late; a missing wake-up never answers
    # early, however often it is tried.
    for attempt in range(5):
        cursor = _cursor(b, waiter)
        begun = time.monotonic()
        thread, answers = _waiting(b, waiter, cursor, 25)
        time.sleep(0.4)
        said = a.post(
            writer,
            EVENTS,
            {"kind": "message", "type": "notice", "to": waiter.id, "body": f"{attempt}"},
        )
        assert said.status_code in (200, 201), said.text
        thread.join(timeout=30)
        took.append(time.monotonic() - begun)
        assert answers and answers[0].status_code == 200, answers
        assert [e["kind"] for e in answers[0].json()["items"]] == ["message"]
        if took[-1] < BEFORE_THE_FALLBACK:
            return
    pytest.fail(f"no wait ended before the fallback read: {took}")


def test_a_second_wait_on_the_other_process_supersedes_the_first(
    hubs: tuple[Hub, Hub], agents: tuple[flow.Agent, flow.Agent]
) -> None:
    (a, b), (_, waiter) = hubs, agents
    # Tried again like the wake-up: a loaded runner may not have opened the first wait yet. A
    # notice that never crosses leaves it open until its own end, with `superseded` false.
    for _ in range(3):
        cursor = _cursor(a, waiter)
        thread, first = _waiting(a, waiter, cursor, 8)
        time.sleep(1)
        newer, second = _waiting(b, waiter, cursor, 1)
        thread.join(timeout=30)
        newer.join(timeout=30)
        assert first and second
        if first[0].json()["superseded"] is True:
            assert second[0].json()["superseded"] is False
            return
    pytest.fail("the older wait was never superseded")


def test_a_rate_limit_counts_once_over_both_processes(
    hubs: tuple[Hub, Hub], agents: tuple[flow.Agent, flow.Agent]
) -> None:
    a, b = hubs
    wrong = {"handle": "maintainer", "password": "not the password at all"}
    # Ten a minute (`LOGIN_BY_HANDLE`), and the in-process login of the setup is one of them:
    # neither process alone sees more than six of its own.
    answers = [
        (a if n % 2 else b).send({}, "POST", "/api/v1/auth/login", json=wrong) for n in range(12)
    ]
    codes = [answer.status_code for answer in answers]
    assert codes[-1] == 429 and 429 not in codes[:8], codes
    assert answers[-1].headers["Maity-Error"] == "rate_limited"


def test_a_signed_requests_nonce_is_refused_on_the_other_process(
    hubs: tuple[Hub, Hub], agents: tuple[flow.Agent, flow.Agent]
) -> None:
    (a, b), (_, agent) = hubs, agents
    headers = signed_by(agent, "GET", "/api/v1/me")
    assert a.send(headers, "GET", "/api/v1/me").status_code == 200
    again = b.send(headers, "GET", "/api/v1/me")
    assert again.status_code == 401
    assert again.headers["Maity-Error"] == "nonce_reused"
