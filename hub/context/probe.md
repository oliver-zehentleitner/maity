# Probe

## The probe runs in a worker thread of the hub process, fed after each report and on an interval

**Id:** c47037e3-21ee-4f14-8a34-0a9a4eb85d82
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-21 (the probe slice)
**See:** https://github.com/oliver-zehentleitner/maity — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-21
**Revisit when:** a second replica runs (each would sweep the same projects), or one sweep takes longer than its interval

A report is stored and answered without touching the forge; its card id
then goes onto the queue of one daemon thread per hub process, which reads
the branch and the pull request and fills `report.observed`. The same
thread sweeps every five minutes: reports of the last day still without an
observation, and the open release of every observable project. Forge reads
happen with no database connection held; each result is written in a short
transaction of its own under the project lock. The thread starts only when
`MAITY_FORGE_GITHUB_TOKEN` is set.

**Reason:** the forge is slow and fallible, and a write must never wait
on it (docs/api.md §6.6). A thread with blocking `urllib` keeps the
probe free of a new dependency and of the event loop: a slow forge cannot
delay a long-poll's wake-up, and it fits the single replica V1 runs.

**Rejected alternatives:**
- FastAPI background tasks after the response: tied to the request, so
  nothing would run the interval sweep, and a retry after a failed read
  would need a second mechanism anyway.
- An asyncio task with an async HTTP client: a new dependency, and every
  database access would have to leave the loop again.
- A separate probe process or cron job: one more thing to deploy and
  supervise for work that takes milliseconds every few minutes.
