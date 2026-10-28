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

## A merge closes the loop: remembered on the card per report, told by whoever sees it first

**Id:** f89f3f4d-28b0-4bda-841a-ddafe87ad18f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.6 "A merge closes the loop" and §6.1 `merged_closes` (contract #502, the coordinator's card tsk-hkb9qe4xn520, 2026-10-28)
**Revisit when:** the hub keeps more than one report per card, or the done authority gains values beyond those of §6.4

The card remembers the report a merge was observed on (`merge_report`, a
digest of the report as the agent sent it) and whether `task_merged` went
out for it (`merge_told`). The probe, where it stores an observation,
tells it when the card is in `review`; the two ways back to `review`
(the status PATCH and the answer that restores a blocked card) tell a
remembered one, only while that report is still the card's. Under
`merged_closes: auto` and `done_authority` `holder` or `admin` the
same step closes the card, unless a child, a dependency or an objection
holds it. `task_merged` wakes by `done_authority`: the holding instance,
the reviewer or tester role, or owners and admins; nobody once closed.

**Reason:** "once per report" and "caught up on the return to review"
must survive a restart and hold whichever path sees the merge first; two
columns on the card are the smallest state that does, and the digest
ties the memory to exactly the report it was seen on.

**Rejected alternative:** asking the event log whether `task_merged`
went out for this report: a search over events on every observation. A
flag inside the report JSON: the report is shown as stored, so the flag
would leak into the card view.

## A spent forge budget stops reads until its reset; the worker waits and starts each round elsewhere

**Id:** d4a944d2-5e48-45e4-a93b-f528f43705ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-wq0mhep8mzec from the coordinator, 2026-10-28, after the live forge reads ran into GitHub's limit; the contract text in PR #500 (§11.4 "Rate limits": one budget per source, `probe_unavailable` with `details.retry_at` until the reset)
**Revisit when:** the hub reads with more than one source per owner (a GitHub App installation, owner tokens), or GitHub changes its rate limit headers

Every forge answer's `X-RateLimit-Limit`, `-Remaining` and `-Reset` (and
`Retry-After`) update one budget per source, keyed by the token's digest
(a separate one for reads without a token). A spent budget (403 or 429
with Remaining 0 or a Retry-After) or one under 5 % of its limit holds
every read with that source until the reset: the read fails at once,
nothing is sent, and the error carries `retry_at`, which `GET …/probe` and
the contract text answer as `details.retry_at` of `probe_unavailable`.
Each read is counted against the source before it is sent, in the same
step as the check, so readers in parallel cannot spend together what the
last answer said was left; answers that arrive out of order only ever
lower the count within one window. The worker schedules its next sweep
and merge round no earlier than that reset, and each kind of round
starts at another project each time, on its own position, since a round
ends at its first unanswered read.

**Reason:** a spent limit answered every read with an error and the
worker asked again every interval, spending the next hour's budget at its
first minute; readers were told nothing about when it would work again.
Keeping the last 5 % leaves room for the reads a person asks for.

**Rejected alternative:** answering from the cache without saying so
while the budget is spent: the card asks for `probe_unavailable` with
the time instead of silently stale data. A budget per project: the limit
is the source's, and every project of an owner reads with it. Other
alternatives: unknown.

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
that is no rate limit, a 404, a redirect, or a GraphQL answer without
the repository or with an error that is no rate limit. A 404 is often
only a ref that is not there, but it cannot be told apart from a
refusal, so the next read asks again. That costs one extra request.

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
