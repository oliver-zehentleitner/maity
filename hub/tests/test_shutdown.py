"""A stopping hub releases its open long-polls at once (hub/context/kubernetes.md)."""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
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


def test_the_stop_signal_hands_the_release_to_the_loop() -> None:
    server = _Server(
        uvicorn.Config(app=lambda *_: None, timeout_graceful_shutdown=GRACEFUL_SECONDS)
    )
    loop = asyncio.new_event_loop()
    try:
        server._loop = loop
        server.handle_exit(signal.SIGTERM, None)
        assert server.should_exit and not longpoll.stopping.is_set()  # not in the handler
        loop.run_until_complete(asyncio.sleep(0))
        assert longpoll.stopping.is_set()  # on the loop, between two callbacks
    finally:
        loop.close()
    assert server.config.timeout_graceful_shutdown == GRACEFUL_SECONDS


CHILD = """
import os, signal, uvicorn
from maity_hub import longpoll
from maity_hub.cli import _Server
server = _Server(uvicorn.Config(app=lambda *_: None))
import asyncio
server._loop = asyncio.new_event_loop()
signal.signal(signal.SIGTERM, server.handle_exit)
with longpoll.registry._lock:  # the signal lands while the registry is locked
    os.kill(os.getpid(), signal.SIGTERM)
print("handler returned", server.should_exit)
"""


def test_a_signal_inside_the_registrys_lock_does_not_hang() -> None:
    done = subprocess.run([sys.executable, "-c", CHILD], capture_output=True, text=True, timeout=10)
    assert done.returncode == 0, done.stderr
    assert "handler returned True" in done.stdout
