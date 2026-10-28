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

## Confirming the repository asks for no step-up until the second factor lands

**Id:** 0b375b9b-2098-4e55-a461-cccdad6a62d1
**Type:** workaround
**Status:** open
**Evidence:** confirmed
**Source:** `docs/api.md` §2.8.4 and §11.4 (the namespace owner confirms "with the step-up"); card tsk-dtpr7zqxhxc2, part 2
**Revisit when:** the second-factor pull request #471 (`second_factor.require_step_up`) is on `main`; card tsk-svg6mfthm7xv

`POST /projects/{owner}/{slug}/repository/confirm` does not call a step-up
yet, because the hub it landed on has no second factor. Whichever of the two
pull requests merges second adds `second_factor.require_step_up(conn, hub,
caller)` before the confirmation is written, plus a test, as for the
transfer. Until then the confirmation opens nothing: no owner grant (App
installation, owner token) is read yet, so `owner_confirmed` is only
stored. The step-up has to be in place before those grants land.
