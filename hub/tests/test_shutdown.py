"""A stopping hub releases its open long-polls at once (hub/context/kubernetes.md)."""

from __future__ import annotations

import signal
import threading
import time
from typing import Any

import uvicorn
from sqlalchemy import Engine

from maity_hub import longpoll
from maity_hub.cli import GRACEFUL_SECONDS, _Server
from tests import flow
from tests.conftest import ClientFactory


def test_an_open_long_poll_answers_when_the_hub_stops(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    latest = agent.get("/projects/maity/events?after=latest").json()["cursor"]
    answers: list[Any] = []
    begun = time.monotonic()
    waiter = threading.Thread(
        target=lambda: answers.append(agent.get(f"/projects/maity/events?after={latest}&wait=30"))
    )
    waiter.start()
    time.sleep(0.5)
    longpoll.begin_shutdown()
    waiter.join(timeout=10)
    assert answers and answers[0].status_code == 200
    body = answers[0].json()
    assert (body["items"], body["superseded"]) == ([], False)
    assert time.monotonic() - begun < 5  # not the 30 seconds it asked for


def test_the_stop_signal_releases_the_long_polls_first() -> None:
    server = _Server(
        uvicorn.Config(app=lambda *_: None, timeout_graceful_shutdown=GRACEFUL_SECONDS)
    )
    assert not longpoll.stopping.is_set()
    server.handle_exit(signal.SIGTERM, None)
    assert longpoll.stopping.is_set() and server.should_exit
    assert server.config.timeout_graceful_shutdown == GRACEFUL_SECONDS
