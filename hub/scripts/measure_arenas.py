"""Measure what the allocator's arena limit does to a real hub (docs: hub/context/packaging.md).

    python hub/scripts/measure_arenas.py [--arenas default 2] [--threads 16] [--requests 150]

With `--grow N` it then sends `--phases` more phases of N requests (four clients) and reports the
process size after each, which shows the growth per request instead of the one jump of the burst.

For each setting it starts a fresh hub on loopback (SQLite in a temporary directory, a
separate process, `MALLOC_ARENA_MAX` set as given), makes an owner and a project with some
messages, warms the hub up, and reads the project's events and lists from `--threads`
concurrent clients, `--requests` each. It reports the process size (`VmRSS` of the hub, from
/proc) before and after, the wall time, the throughput and the latency percentiles. One hub
at a time, so the memory it needs is one hub's (about 150 MB) plus the clients.

A run is valid only if every request was answered: the script counts the failed requests of
each phase, leaves them out of the throughput and the latencies, says how many there were, and
exits with 1 (marking the setting INVALID) if there was one. The environment is cleaned of
`GLIBC_TUNABLES`, `LD_PRELOAD` and `MALLOC_*` first, since they change the allocator under test.
What it shows is limited: a few concurrent clients on a few CPUs against a SQLite database say
nothing certain about the production pod (40 request threads, 2 vCPU, a server database).

Run it from the repository root with the hub installed (pip install -e hub). Linux only.
"""

from __future__ import annotations

import argparse
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_wait import PASSWORD, Human, wait_for_health  # noqa: E402

PORT = 18830


def rss_mib(pid: int) -> float:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def hub_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "maity_hub", *args]


def run_setting(arenas: str, threads: int, requests: int, grow: int, phases: int) -> dict[str, Any]:
    port = PORT + (0 if arenas == "default" else int(arenas))
    hub = f"http://127.0.0.1:{port}"
    work = Path(tempfile.mkdtemp())
    env = dict(
        os.environ, MAITY_DATABASE_URL=f"sqlite:///{work}/hub.db", MAITY_BIND=f"127.0.0.1:{port}"
    )
    for name in [n for n in env if n.startswith("MALLOC_")] + ["GLIBC_TUNABLES", "LD_PRELOAD"]:
        env.pop(name, None)  # they change the allocator under test
    if arenas != "default":
        env["MALLOC_ARENA_MAX"] = arenas
    subprocess.run(hub_command("migrate"), env=env, check=True, capture_output=True)
    subprocess.run(
        hub_command("owner", "create", "--handle", "owner", "--display-name", "Owner"),
        input=PASSWORD + "\n",
        text=True,
        env=env,
        check=True,
        capture_output=True,
    )
    server = subprocess.Popen(
        hub_command("serve"), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        wait_for_health(hub)
        human = Human(hub)
        human.login()
        human.call("POST", "/projects", {"slug": "measure", "name": "Measure"})
        base = "/projects/owner/measure"
        for n in range(30):
            human.call(
                "POST",
                f"{base}/events",
                {"kind": "message", "type": "notice", "to": "all", "body": f"message {n}"},
            )
        paths = [f"{base}/events?after=0&wait=0&limit=50", "/projects", f"{base}/members"]

        def work_loop(count: int, latencies: list[float], failures: list[str]) -> None:
            for i in range(count):
                started = time.perf_counter()
                try:
                    human.call("GET", paths[i % len(paths)])
                except Exception as error:
                    # not a sample: counted and reported, by kind (HTTP status or exception)
                    status = getattr(error, "code", None)
                    failures.append(f"HTTP {status}" if status else type(error).__name__)
                    continue
                latencies.append(time.perf_counter() - started)

        def burst(count: int, clients: int) -> tuple[list[float], list[str], float]:
            found: list[list[float]] = [[] for _ in range(clients)]
            failed: list[list[str]] = [[] for _ in range(clients)]
            pool = [
                threading.Thread(target=work_loop, args=(count, found[t], failed[t]))
                for t in range(clients)
            ]
            started = time.perf_counter()
            for thread in pool:
                thread.start()
            for thread in pool:
                thread.join()
            wall = time.perf_counter() - started
            return [x for part in found for x in part], [k for f in failed for k in f], wall

        errors: dict[str, list[str]] = {}
        _, errors["warm-up"], _ = burst(max(10, requests // 5), threads)
        before = rss_mib(server.pid)
        latencies, errors["burst"], wall = burst(requests, threads)
        after = rss_mib(server.pid)
        growth = [after]
        for phase in range(phases if grow else 0):
            _, errors[f"growth {phase + 1}"], _ = burst(grow // 4, 4)
            growth.append(rss_mib(server.pid))
        ordered = sorted(latencies)
        return {
            "arenas": arenas,
            "rss_before_mib": before,
            "rss_after_mib": after,
            "wall_s": wall,
            "per_s": len(latencies) / wall,
            "p50_ms": statistics.median(ordered) * 1000,
            "p95_ms": ordered[int(len(ordered) * 0.95) - 1] * 1000,
            "p99_ms": ordered[int(len(ordered) * 0.99) - 1] * 1000,
            "n": len(latencies),
            "growth": growth,
            "errors": errors,
        }
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()  # no process is left behind
            server.wait()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arenas", nargs="+", default=["default", "2"])
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--requests", type=int, default=150, help="per thread")
    parser.add_argument("--grow", type=int, default=0, help="requests per growth phase")
    parser.add_argument("--phases", type=int, default=5)
    args = parser.parse_args()
    print(
        f"python {sys.version.split()[0]}, {os.cpu_count()} cpus, "
        f"{args.threads} threads x {args.requests}"
    )
    invalid = False
    for arenas in args.arenas:
        r = run_setting(arenas, args.threads, args.requests, args.grow, args.phases)
        failed = sum(len(kinds) for kinds in r["errors"].values())
        print(
            f"arenas={r['arenas']:>7}  "
            f"rss {r['rss_before_mib']:.1f} -> {r['rss_after_mib']:.1f} MiB  "
            f"{r['n']} requests in {r['wall_s']:.1f}s = {r['per_s']:.0f}/s  "
            f"latency p50 {r['p50_ms']:.0f} ms, p95 {r['p95_ms']:.0f} ms, "
            f"p99 {r['p99_ms']:.0f} ms  failed: {failed}",
            flush=True,
        )
        if args.grow:
            steps = " -> ".join(f"{mib:.1f}" for mib in r["growth"])
            print(f"           after each {args.grow} more requests: {steps} MiB", flush=True)
        if failed:
            invalid = True
            where = "; ".join(
                f"{phase}: "
                + ", ".join(f"{kind} x{kinds.count(kind)}" for kind in sorted(set(kinds)))
                for phase, kinds in r["errors"].items()
                if kinds
            )
            print(f"           INVALID: failed requests ({where}); do not compare this setting")
    return 1 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
