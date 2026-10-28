"""Measure the wake primitive end to end: `maity wait` against a real hub.

    python hub/scripts/measure_wait.py [--rounds 20] [--port 18790] [--database-url URL]

Needs `maity-hub` and `maity` on PATH (pip install -e hub -e cli). Starts a
fresh hub on loopback (SQLite in a temporary directory), a human, a project
and one agent joined with the CLI, then reports three things:

1. latency — from the moment the human's message is committed (its POST
   answered) to the moment `maity wait` exits with it, over N rounds;
2. a proxy idle cut — `maity wait` through a TCP proxy that drops every
   connection after a few seconds, as a reverse proxy's idle timeout would;
   the message comes after the first cut, and the wait must still wake on it;
3. one long-poll per credential — a second `maity wait` in the same clone
   supersedes the first, which exits 6, while the second wakes normally.

Nothing here is mocked: the hub, the CLI and the proxy are separate processes
talking HTTP over loopback.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import http.cookiejar
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

PASSWORD = "measure owner password"
CUT_AFTER = 3.0  # seconds the proxy lets a connection live


class Human:
    def __init__(self, hub: str) -> None:
        self.hub = hub
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.csrf = ""

    def call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.hub}/api/v1{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.csrf:
            request.add_header("X-CSRF-Token", self.csrf)
        with self.opener.open(request, timeout=30) as response:
            return json.loads(response.read() or b"null")

    def login(self) -> None:
        self.call("POST", "/auth/login", {"handle": "owner", "password": PASSWORD})
        self.csrf = self.call("GET", "/auth/session")["csrf_token"]


def run(*args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def wait_for_health(hub: str) -> None:
    for _ in range(100):
        with contextlib.suppress(OSError):
            urllib.request.urlopen(f"{hub}/api/v1/health", timeout=1).read()
            return
        time.sleep(0.1)
    raise SystemExit("the hub did not come up")


class CuttingProxy:
    """Forwards loopback TCP and closes every connection after CUT_AFTER seconds."""

    def __init__(self, listen: int, target: int) -> None:
        self.listen, self.target = listen, target
        self.cuts = 0
        self.loop = asyncio.new_event_loop()

    async def _pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(Exception):
            while data := await reader.read(65536):
                writer.write(data)
                await writer.drain()

    async def _handle(self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
        server_r, server_w = await asyncio.open_connection("127.0.0.1", self.target)
        pipes = asyncio.gather(self._pipe(client_r, server_w), self._pipe(server_r, client_w))
        try:
            await asyncio.wait_for(pipes, CUT_AFTER)
        except TimeoutError:
            self.cuts += 1
        for writer in (client_w, server_w):
            writer.close()

    def start(self) -> None:
        async def serve() -> None:
            server = await asyncio.start_server(self._handle, "127.0.0.1", self.listen)
            async with server:
                await server.serve_forever()

        threading.Thread(target=self.loop.run_until_complete, args=(serve(),), daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument("--database-url", help="an empty database; default: SQLite in a temp dir")
    args = parser.parse_args()
    port, proxy_port = args.port, args.port + 1
    hub, proxied = f"http://127.0.0.1:{port}", f"http://127.0.0.1:{proxy_port}"

    work = Path(tempfile.mkdtemp())
    database = args.database_url or f"sqlite:///{work}/hub.db"
    env = dict(os.environ, MAITY_DATABASE_URL=database, MAITY_BIND=f"127.0.0.1:{port}")
    run("maity-hub", "migrate", env=env)
    subprocess.run(
        ["maity-hub", "owner", "create", "--handle", "owner", "--display-name", "Owner"],
        input=PASSWORD + "\n",
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    server = subprocess.Popen(
        ["maity-hub", "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_for_health(hub)
        human = Human(hub)
        human.login()
        human.call("POST", "/projects", {"slug": "measure", "name": "Measure"})

        def joined(handle: str, via: str) -> tuple[Path, str]:
            created = human.call(
                "POST",
                "/projects/measure/joins",
                {"agent": {"handle": handle, "display_name": handle}},
            )
            clone = work / handle
            run("git", "init", "-q", str(clone))
            url = created["join_url"].replace(hub, via)
            run(
                "maity",
                "join",
                url,
                "--code",
                created["code"],
                "--harness",
                "measure",
                "--no-pointer",
                cwd=clone,
            )
            return clone, created["agent_id"]

        def chat(agent_id: str, body: str) -> float:
            human.call(
                "POST", f"/projects/measure/conversations/{agent_id}/messages", {"body": body}
            )
            return time.monotonic()  # the POST answered: the event is committed

        # 1. latency
        clone, agent_id = joined("direct", hub)
        latencies = []
        for i in range(args.rounds):
            wait = subprocess.Popen(
                ["maity", "wait", "--one", "--timeout", "30"], cwd=clone, stdout=subprocess.PIPE, text=True
            )
            time.sleep(0.6)  # let it reach the hub and start holding
            committed = chat(agent_id, f"round {i}")
            out, _ = wait.communicate(timeout=30)
            woke = time.monotonic()
            assert wait.returncode == 0 and f"round {i}" in out, (wait.returncode, out)
            latencies.append((woke - committed) * 1000)
        latencies.sort()
        p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
        print(
            f"1. latency over {args.rounds} rounds (message committed -> maity wait exited): "
            f"median {statistics.median(latencies):.0f} ms, p95 {p95:.0f} ms, "
            f"max {latencies[-1]:.0f} ms"
        )

        # 2. a second wait of the same credential supersedes the first
        first = subprocess.Popen(
            ["maity", "wait", "--one", "--timeout", "30"],
            cwd=clone,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(1.0)
        second = subprocess.Popen(
            ["maity", "wait", "--one", "--timeout", "30"], cwd=clone, stdout=subprocess.PIPE, text=True
        )
        first_out, first_err = first.communicate(timeout=15)
        time.sleep(0.5)
        chat(agent_id, "for the second")
        second_out, _ = second.communicate(timeout=30)
        print(
            f"2. superseded: first maity wait exit {first.returncode} ({first_err.strip()!r}), "
            f"second exit {second.returncode}, "
            f"second woke on its message: {'for the second' in second_out}"
        )
        # 3. a proxy that cuts every connection after CUT_AFTER seconds
        proxy = CuttingProxy(proxy_port, port)
        proxy.start()
        time.sleep(0.2)
        clone_p, agent_p = joined("proxied", proxied)
        # The CLI keeps the hub URL the exchange named (Maity-Hub); route it through the proxy.
        state_file = clone_p / ".git" / "maity" / "state.json"
        state = json.loads(state_file.read_text())
        state["hub"] = proxied
        state_file.write_text(json.dumps(state))
        wait = subprocess.Popen(
            ["maity", "wait", "--one", "--timeout", "30"],
            cwd=clone_p,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(CUT_AFTER * 3 + 1.0)  # several connections cut before the message
        cuts_before = proxy.cuts
        committed = chat(agent_p, "after the cut")
        out, err = wait.communicate(timeout=40)
        woke = time.monotonic()
        ok = wait.returncode == 0 and "after the cut" in out
        print(
            f"3. proxy idle cut every {CUT_AFTER:.0f} s: "
            f"{cuts_before} connection(s) cut before the message, "
            f"maity wait exit {wait.returncode}, woke on the message: {ok}, "
            f"{(woke - committed) * 1000:.0f} ms after the commit"
        )
        if not ok:
            print(err, file=sys.stderr)

        return (
            0 if ok and cuts_before >= 1 and first.returncode == 6 and second.returncode == 0 else 1
        )
    finally:
        server.terminate()  # exactly this process, never by pattern
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
