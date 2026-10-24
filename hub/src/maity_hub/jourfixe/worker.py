"""The jour fixe's clock (docs/api.md §20.1): the presence minutes, the schedule's slots
and the deadlines, acted on in the background once a minute. A deadline that passed while
the hub was down is acted on when it is back."""

from __future__ import annotations

import logging
import threading

from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import transaction
from maity_hub.jourfixe import rounds

log = logging.getLogger(__name__)
INTERVAL = 30.0  # seconds; tests set it out of reach and call `sweep` themselves


def sweep(engine: Engine) -> None:
    with transaction(engine) as conn:
        rounds.record_presence(conn, clock.now())
        project_ids = list(conn.execute(select(t.project.c.id).order_by(t.project.c.id)).scalars())
    for project_id in project_ids:
        try:
            with transaction(engine) as conn:
                rounds.handle_deadlines(conn, project_id)
                rounds.handle_schedule(conn, project_id)
        except Exception:  # one project's failure must not stop the others
            log.exception("the jour fixe sweep of %s failed", project_id)


class Worker:
    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval  # read now: tests set it
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-jour-fixe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sweep(self.engine)
            except Exception:
                log.exception("the jour fixe sweep failed")
