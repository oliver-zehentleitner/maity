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
thread sweeps every five minutes: reports still without an observation on
open cards of any age and on cards closed within a day, and the open
release of every observable project. A round ends at the first read the
forge does not answer, and between two reads when the hub stops. Forge reads
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

## A change is detected where the observation is written, by whichever read sees it first

**Id:** 971bbd15-a0d5-441b-b625-11bbe1b0d961
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-22, after the coordinator's review of PR #36 reproduced a lost `probe_observed`
**See:** probe.md — c47037e3-21ee-4f14-8a34-0a9a4eb85d82 — as of 2026-10-22
**See:** releases.md — ffc30b1f-9412-45f7-94c7-b02c8552c0a7 — as of 2026-10-22
**Revisit when:** observations are kept per repository, or a second replica writes them

Three readers write the same `forge_observation` row: `GET /probe`, a
report's own probe and the worker's sweep. `observe()` compares the new
reading with the stored one under the project lock, in the transaction
that replaces the row. When the state differs (found, state, head,
checks, mergeability, merge time, tag sha) and the ref belongs to the open
release, `probe_observed` goes out on the release card there, and release
readiness is rechecked in the same transaction. A slower read that started
before a newer one was written does not replace it.

**Reason:** the first version compared in the sweep, against the row as
it found it. When `GET /probe` had read a merge first, the sweep saw no
difference: no `probe_observed`, and `release_ready` only one sweep (300 s)
later. The row is the one place every reader passes through.

**Rejected alternatives:**
- Keeping the last announced state on the release card and diffing
  against that in the sweep: correct, but `release_ready` would still wait
  for the next sweep after a `GET /probe` had seen the merge.
- One `probe_observed` per sweep with all changed refs, as before: fewer
  events, but only the sweep could send them.

## The public-only check sits in the one place every read with the token passes

**Id:** a91a5a3d-a29a-4c9e-9721-d01d89aeacd2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-28 (card tsk-dtpr7zqxhxc2, part 1)
**Revisit when:** the owner's grants (§11.4: App installation, owner token) land and a read picks its source before it is made

The operator's token reads only repositories the forge reports public
(docs/api.md §11.4). `Forge._call` checks this before every request it
makes with the token. It takes the repository from the request itself:
the `/repos/{owner}/{name}` path, or the GraphQL variables. A read that
names no repository is not made with the token. The answer is kept for
10 minutes per token and repository, a refusal included. A visibility
the forge does not give is not kept, and the next read asks again.
A read the forge refuses drops a kept "public" at once: a 401 or a 403
that is no rate limit, a redirect, or a GraphQL answer without the
repository. A 404 is often an answer (a ref that is not there), so it
drops nothing by itself. `_missing` asks again instead, as part of
checking that the repository is still visible.

**Reason:** the probe worker, the ticker, the images, the Keep the Why
walk, card links and contract texts all read through `Forge`. A check
in the request path covers each of them, and any read added later. A
check per method or per route would have to be repeated in each one,
and a single forgotten one would read a private repository.

**Rejected alternatives:**
- A check in the routes before the read: the workers read without a
  route, so they would not be covered.
- A check in each `Forge` method: correct today, but a new method that
  forgets it reads with the token unchecked.
