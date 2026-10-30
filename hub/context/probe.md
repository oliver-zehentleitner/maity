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

## The forge's per-token maps drop what says nothing, and keep at most a bound

**Id:** 305001eb-e4bf-4170-aea9-011bec960cef
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-7865c6c2gszb (the hub's in-process structures without a bound), the lead's ruling, 2026-10-29; the review of #671 (the gate's trade-off, the scan's cost); `hub/tests/test_forge.py` (`test_budgets_that_say_nothing_go_beyond_the_kept_number`, `test_a_visibility_cache_drops_stale_entries_and_keeps_at_most_the_bound`)
**Revisit when:** the load test (tsk-ryas52q9k53z) or prod's memory curve shows the bounds (256 budgets, 4096 visibility entries) too small or too large

The budgets (`forge._budgets`), the visibility of a repository to a
token (`_visible`) and its publicness (`_public`) are keyed by a token's
digest. Installation tokens are minted anew every hour, so these maps
gained keys for as long as the process ran, and nothing removed them.

- **Budgets:** once more than `BUDGETS_KEPT` (256) sources are known, a
  read drops every budget that says nothing any more. That is one with
  nothing in flight, no hold, and no `remaining` that still counts
  (none, or its window over). Such a budget answers exactly as a new
  `_Budget()` would, so dropping it changes no answer. A budget still
  in use is never dropped, whatever the count.
- **Visibility and publicness:** a write first drops the entries past
  their time (300 s and 600 s), then the oldest written beyond
  `CACHE_KEPT` (4096). A dropped entry costs one more read of
  `/repos/{repository}`, nothing else. The writes and the `_forget` of
  `_public` go under one lock, since the probe's worker and the requests
  write them from different threads.
- **A contract text read's gate** (`contract_text._pending`) goes in a
  `finally`, also when the forge did not answer. Every new commit is a
  new key, so a gate kept after a failure would stay for good. Accepted
  in return: after a failed read, a request still waiting on the old
  gate and a new one with a new gate may both read the forge at once.

The numbers are a first estimate: far above what a single instance uses
today, and small enough to stay a few MB at most. Above `BUDGETS_KEPT`,
while every budget is in use, each read scans the whole map under
`_budgets_lock` (O(n) per read). That is negligible at today's counts,
and part of what the revisit weighs.

**Rejected alternatives:**
- A plain LRU for the budgets: it could drop a budget that still holds
  its source until the reset, and the next read would then go out into a
  spent limit.
- A sweeping thread on a timer: one more thread for what the write
  itself can do.

## Confirming the repository asks for no step-up until the second factor lands

**Id:** 0b375b9b-2098-4e55-a461-cccdad6a62d1
**Type:** workaround
**Status:** superseded
**Superseded by:** none — the workaround ended: with #471 on `main`, the confirmation, starting a link and storing a token all call `second_factor.require_step_up` (#525)
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

## A link's state is a stored random value, not a signature

**Id:** 6d8bdf23-78c7-49fd-b122-966f127a46d6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §11.4 (as changed with the contract pull request #524); card tsk-dtpr7zqxhxc2, part 3
**Revisit when:** links have to start without a database write, for example from a second hub instance that shares no database

`POST /me/forge/github/link` hands the forge a `state` of 256 random
bits. The hub stores only its hash, bound to the session that started
the link, valid 15 minutes, and deletes the row when it is used.
`GET /forge/github/setup` takes the state in its own transaction before
it asks the forge anything. A state of another human or another session
is refused and stays usable for the session it belongs to.

**Reason:** "usable once" needs a stored record whatever the state
looks like. Once that record exists, a signature adds no check that the
stored hash does not already make, and the hub would need a key for it.

**Rejected alternatives:**
- A state signed with an instance key (the contract's first wording):
  it still needs the stored record for single use, and adds a key to
  manage.

## A project's source is chosen per project, and a grant is bound to its repository

**Id:** a5b07f08-306e-4f33-8643-8b59af50dd71
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-28 (card tsk-dtpr7zqxhxc2, part 5a)
**Revisit when:** organisations become namespace owners (§6.25), or one repository serves projects of several owners with different grants and that needs one shared read

`Forge.for_project` chooses the reader of one project (`forge_access.py`).
Every place that reads calls it with the project it reads for: the probe,
reports, releases, the ticker, deploys, card links, images, Keep the Why
and contract texts. A grant's reader carries the one repository it was
chosen for. A read of any other repository goes out without a token
(public only), and a GraphQL read of another repository is refused. The
choice is kept for at most 10 minutes. Its key is everything it depends
on: the URL, the owner, the confirmation, the owner's links and token,
and the operator's token. A change of any of them, or a refused read,
chooses again.

**Reason:** the same repository URL can be set on projects of different
namespace owners. A choice keyed by the repository would let one owner's
grant read for another owner's project. That is the leak §11.4 exists to
prevent.

**Rejected alternatives:**
- One resolver per repository inside `Forge._call`: no call site would
  need to change, but the project, and with it the owner whose grant
  counts, would be lost.
- Choosing inside the views (for `probe_via`): a view holds a database
  connection, and the choice would ask the forge. The view shows the
  last choice instead (`forge_access.probe_via`), and before any
  choice the operator's token if there is one.

## A page without sign-in counts only merges a read found public

**Id:** 6af0bb67-32dd-40df-91df-df1eb03288fc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §11.4 ("What a private repository's data may reach") and the event table, §8.2; the lead's decision on card tsk-dtpr7zqxhxc2, part 5b
**Revisit when:** another page without sign-in shows data the probe read, or the forge stops reporting visibility in the GraphQL read

`link_observed` carries `public`: whether the same GraphQL read reported
the repository public (`isPrivate: false`), `false` when it did not say.
The swarm page counts merged pull requests only from events with
`public: true`. Events written before the field existed do not count.

**Reason:** the flag follows what the read itself saw, not which token
made it. With the token as the test, a public repository read with an
App or owner token would never count, and a repository that turned
private between two reads would still count. The old events go
uncounted on purpose: before the instance token was limited to public
repositories, it could read private ones too, so those events cannot
prove they were public. Privacy goes before the statistic.

**Rejected alternatives:**
- `public` from the source (`via == "instance"`): it leaves out public
  repositories read with an owner's grant.
- Counting events without the field: it may count merges of private
  repositories read before the instance token was limited.
