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
thread sweeps every five minutes: reports without an observation on open
cards of any age and on cards closed within a day, the open release of
every observable project, then the 15 reports with the oldest observation
whose pull request was last seen open. A round ends at the first read the
forge does not answer, and between two reads when the hub stops. A project
no source covers (`NotCoveredError`) is no such read: only its own work is
left out, it logs its id, and its reports don't count against the 15. Ending
the round there stopped every round from reaching the re-reads, in production
for as long as one project lacked a grant. A stored repository URL that names
no valid repository (`InvalidRepositoryError`, a URL stored before the write
checked it) is that project's own fault just the same and is left out the same
way, on every path: the check runs before any branch reads the path and before
the read counts against the source's budget, so a refusal ends no round and
holds no budget. Every GraphQL read of the hub names its repository in its
`owner` and `name` variables; one that does not is refused, so no read skips
the check. Forge reads
happen with no database connection held; each result is written in a short
transaction of its own under the project lock. The thread starts only when
`MAITY_FORGE_GITHUB_TOKEN` is set.

**Reason:** the forge is slow and fallible, and a write must never wait
on it (docs/api.md §6.6). A thread with blocking `urllib` keeps the
probe free of a new dependency and of the event loop: a slow forge cannot
delay a long-poll's wake-up, and it fits the single replica V1 runs.

**Rejected alternatives:**
- Ending the round at a project no source covers, like at any forge failure: one such project stopped every round before the re-reads.
- Counting its report against the 15 re-reads: it stays the oldest, so such projects could use up all 15. The refusal itself is cached for 600 seconds per token and repository (§11.4), so a project left out costs at most one read of the repository in that time.
- FastAPI background tasks after the response: tied to the request, so
  nothing would run the interval sweep, and a retry after a failed read
  would need a second mechanism anyway.
- An asyncio task with an async HTTP client: a new dependency, and every
  database access would have to leave the loop again.
- A separate probe process or cron job: one more thing to deploy and
  supervise for work that takes milliseconds every few minutes.

## A report's observation wakes an admin only on a mismatch, and a closed card wakes nobody once merged

**Id:** 75682de7-9b2e-415b-acf9-8339bc157231
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-cq0mzfrbswb7, observed on production on 2026-11-01 after #1083 reached old cards; `events.wakes`, `readable_by`, docs/api.md §8.2
**Revisit when:** an admin has to act on an observation without a mismatch

The sweep of old cards after #1083 woke every admin about every 2 seconds, one event per card. Each event was a real change (`open` to `merged`), so comparing with the last reading did not help, and the same audience also woke the admins on every report and every change of `checks`. `probe_observed` now names `trust:admin` only with `mismatch: true`. A closed card names nobody without a mismatch or with its pull request merged: the same sweep showed `mismatch: true` on a done card whose head moved after its last report and was merged, which nobody has to act on. It stays readable on the card's report. A closed card whose pull request is missing or closed unmerged still wakes. An event can have no audience at all. The observation of the open release keeps its audience: it is few events, and a release waits on them.

**Reason:** owners and admins read every event without being named, and being named is what wakes them, so the dashboard and the event list lose nothing. A merge already reaches who must act as `task_merged`.

**Rejected alternatives:**
- Not emitting the event for a merged or done card: the dashboard re-reads on it, and the record of the observation would be gone.
- A new entry in `NON_WAKING`: it is per kind, and a mismatch has to wake.
- Rate limiting the sweep's events: fewer wake-ups, but each still costs every admin a run for nothing to do.

## A sweep reads a report again while its pull request was last seen open

**Id:** 9092661c-3553-4e0f-81d1-fa521fa05581
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-bex2nzwmceh8, 2026-11-01
**Revisit when:** a verified `pull_request` delivery refreshes the report itself, or the forge budget (§11) cannot carry these reads

Until 2026-11-01 a sweep read only reports without an observation, so a
report first seen with its pull request open stayed `open` after the
merge: `task_merged` and `merged_closes` (§6.6) never fired for it, and
`maity report` refused a follow-up pull request on the card because the
last one looked open. The tests called `observe_report` directly on a merged pull
request, so none noticed. A sweep now also reads reports last seen open, up
to 15 a round, oldest observation first, after everything else it reads.

**Reason:** the contract's "A merge closes the loop" needs someone to look
again, and the sweep is the only reader that runs on its own.

**Consequence:** one report costs at least four forge requests (branch, pull
request, check runs, statuses), so about 60 per sweep and 720 an hour, some 14%
of a 5000-an-hour source, with no cache help since the 60 s of `MAX_AGE` are
shorter than the sweep. A forgotten open pull request on an open card keeps
its turn at any age. Beyond 15 such reports a merge shows later: one round
per 15 reports, so 150 reports take up to 50 minutes. A merge into the default
branch is still announced by the ticker in that time; only the card lags.

**Rejected alternatives:**
- Refreshing from the merge ticker alone: it sees only merges into the
  default branch, and a pull request closed unmerged or merged into another
  base would stay open on its card.
- A turn counter per process, as `_rotated` keeps: it restarts with the
  process and each replica would count alone, while the oldest `observed_at`
  needs no state of its own.
- Reading every such report each round: about 48 requests an hour per report
  would use a 5000-an-hour source up at about 100 of them, and as the round
  ends at the first unanswered read, releases and links behind them would
  starve.

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
**Source:** docs/api.md §6.6 "A merge closes the loop" and §6.1 `merged_closes` (contract #502, the coordinator's card tsk-hkb9qe4xn520, 2026-10-28); the close only for the card whose pull request it is by card tsk-yfv9rnxpcwjd (2026-11-20, context/reports.md d068e91d-bf97-44e3-ba98-0f1c7e5b3674)
**Revisit when:** the hub keeps more than one report per card, or the done authority gains values beyond those of §6.4

The card remembers the report a merge was observed on (`merge_report`, a
digest of the report as the agent sent it) and whether `task_merged` went
out for it (`merge_told`). The probe, where it stores an observation,
tells it when the card is in `review`; the two ways back to `review`
(the status PATCH and the answer that restores a blocked card) tell a
remembered one, only while that report is still the card's. Under
`merged_closes: auto` and `done_authority` `holder` or `admin` the
same step closes the card, unless a child, a dependency or an objection
holds it, or the pull request is not the card's own (`merged._not_its_own`:
its head branch from the stored `pr` observation, the card ids its text
names, its merge time against the report's, and the other cards' reports
and closed `task_merged` events, read only before a close). `task_merged` wakes by `done_authority`: the holding instance,
the reviewer or tester role, or owners and admins; nobody once closed.

**Reason:** "once per report" and "caught up on the return to review"
must survive a restart and hold whichever path sees the merge first; two
columns on the card are the smallest state that does, and the digest
ties the memory to exactly the report it was seen on.

**Rejected alternative:** asking the event log whether `task_merged`
went out for this report: a search over events on every observation. A
flag inside the report JSON: the report is shown as stored, so the flag
would leak into the card view.

## A merge closes outsiders' work on its own only with its own approvals

**Id:** 35bf91b0-7944-448b-a876-0e549696d410
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-997vnv5efkw9 (2026-11-23), the lead's go on the plan (seq 201169) and the order to key it on the owner's membership until trust `outside` lands (seq 201228); docs/api.md §2.3 "Own approvals" and §6.6 "A merge closes the loop"
**See:** probe.md#a-merge-closes-the-loop-remembered-on-the-card-per-report-told-by-whoever-sees-it-first — f89f3f4d-28b0-4bda-841a-ddafe87ad18f — as of 2026-11-23
**Revisit when:** a merge can close a card by a path that does not pass `merged._blocked_by`

Under `merged_closes: auto` a merge does not close outsiders' work
without its own approvals: `merged._blocked_by` adds `own_approvals` when
`own_approvals.missing` finds the card is outsiders' work (an outside
agent holds it or filed its current report, judged as the members stand
when the merge is seen) with fewer own approvals on the reported head
than `policy.own_approvals`, and `task_merged` then says `closed: false`
and wakes the done authority as under `notify`. With them, the merge
closes it as any other card. The first version (tsk-997vnv5efkw9) came
before the count existed and held every such card; the gate's count
(tsk-3ggnhdmgmkf3, trust.md 3ebd6d4a) replaced that, as this entry
planned.

**Reason:** `auto` under `done_authority: holder` would otherwise let an
outside holder's own merge close its own card, with no member of the
project having approved what it delivered. Holding the close on this path
until the count says so leaves the decision with the done authority,
which `task_merged` already wakes.

**Rejected alternatives:**
- Leave the merge path until the whole gate is built: until then an
  outside holder under `auto` closes its own work on a merge.
- Count own approvals here: that counting is the core of the gate card
  and would exist twice; this check is one call into it
  (`own_approvals.missing`), which reads trust `outside`, the
  `joined_outside` mark and the owner's membership.
- A `blocked_by` value of its own (`outside_work`): the gate refuses a
  move to `done` with the reason `own_approvals`, and one name for the
  same missing approval reads the same in both places.

## A spent forge budget stops reads until its reset; the worker waits and starts each round elsewhere

**Id:** d4a944d2-5e48-45e4-a93b-f528f43705ed
**Type:** decision
**Status:** needs-review
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
  `/repos/{repository}`, nothing else. The writes and the `forget_visibility` of
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
**Status:** needs-review
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
**Status:** needs-review
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

## A link on a forge organisation keeps its last success apart from its last check, and one process claims each check

**Id:** aa664ec0-22da-4cca-bf1e-f44f41ebbfe9
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of hub PR 2 of card tsk-2m5jbwemb21x, 2026-11-24, on the plan note nte-cm5qr3y8bx04; the lead's go of 2026-11-24 (seq 214797: the claim by a conditional update of `checked_at`, its two-connection test, rulings Q2 and Q3); the review notes A2509 (213241) and A2510 (nte-e0amanaa564s) on the contract pull request #2139; the security review A2545 of hub PR 2 (seq 215798) and the lead's rulings and go on it (seqs 215805, 215921); contract `docs/api.md` §11.4
**See:** https://github.com/oliver-zehentleitner/maity — 40057878-5f35-44fa-8b67-2e1820b59d38 — as of 2026-11-24
**Revisit when:** the hub keeps the owner check's outcome anywhere but `forge_link`, the App's events replace the polling, or a second kind of check gets its own cadence

How the owner check of §11.4 is built (`forge_links.py`, `forge_access.py`):

- `forge_link.owner_ok_at` holds the last successful owner check, apart
  from `checked_at`, the last check whatever came of it. A link on a
  forge organisation serves only while `active` and `owner_ok_at` is
  under 10 minutes old (`forge_links.serves`). A success counts from
  when its check was claimed, never from when it ended; the one at
  linking from before `verify` reads the user's own membership
  (`owner_checked_at`, passed to `link`), never from the insert, on a
  replacement too (review A2544).
- A due check is claimed by one conditional `UPDATE … SET checked_at =
  now WHERE checked_at <= now - 10 minutes`, committed before any forge
  call; the process whose update changed the row makes the check, every
  other one takes the link as it stands. Its forge reads hold no
  connection. Checked live on PostgreSQL 16 and MariaDB 11.4 in review
  A2544: of eight concurrent claims of one due link, exactly one won.
- A refused mint on such a link sets its status but not `checked_at`,
  and a `suspended` one is minted for only inside its check: a mint is
  no owner check, and the check's first step reads the suspension
  itself.
- The token a check mints for a link that does not serve already is
  neither taken from nor put into the held tokens (`token(keep=False)`).
- The reasons such a link gives (`errors.ORG_*`) are the hub's own and
  never reach an answer as they are: every reader answers them through
  `errors.forge_refusal`, which knows who is the human in
  `confirmed_by` (that human themselves, never their agent).
- The source choice is kept no longer than the link's check: until 10
  minutes after its success while it serves, until its next check is
  due while it does not, besides the usual 10 minutes and key.
- §11.3's export asks the source on every call only where it rests on
  such a link, and refuses by reader only while that link serves
  nothing and no other source covers; every other state is answered
  from its cache as before. Two cases around such a link answer
  `ktw_unavailable` with `forge_unavailable` and without `details.last`
  instead of the cache (`probe_unavailable` with `details.retry_at`
  while the budget is spent): the operator's token after it cannot read
  the visibility, and the choice itself has no answer while the owner's
  grants hold such a link (the reader then carries `ORG_UNANSWERED`).
  Any refusal of that visibility, `repository_moved` included, is
  answered by reader, never from the cache (A2574 P2-2). Unlinking or
  replacing such a link, and its leaving `active` (`not_admin`,
  `suspended`, `removed`), drops the Keep the Why reads of the human's
  projects on every replica, since the choice may then refuse with
  `no_grant`, which §11.3 does not ask about (review A2545 #5, A2574
  P2-3).
- An export read through such a link is kept with the time its grant
  ends (`serves_until`, the success plus 10 minutes): past it the
  cache answers it nowhere, the project view's `keep_the_why_export`
  included, a failed read afterwards keeps none of it, and no member
  falls back on a last good read made through it (A2574 P2-3).
- The probe asks the operator's token's visibility on every call before
  a cached observation is answered, as §11.5 does: after such a link
  that serves nothing (A2545 #6) and after one that was unlinked,
  replaced or removed on the forge, which leaves no reason behind (A2574
  P2-1). A visibility without an answer is `probe_unavailable` without
  `details.last`.
- A forge answer whose ids are no numbers (a JSON `true` included) or
  whose names are empty is no answer, never a "no" or a match: the
  installation, the user, the membership, and the ids `is_owner`
  compares; step 1 naming another account than the link's is no answer
  either (A2545 #4).
- A replacement rereads the existing link under its row lock after the
  check and compares it with the link the check was made for, before
  anything else: any difference, an unlink, a removal and a link of the
  caller's own meanwhile included, is `forge_unavailable` with nothing
  written and no retry (the lead's ruling Q2; review A2545 #1). Its
  check mints a token for its own reads alone, and a replacement drops
  the installation's held tokens on every replica (A2545 #7).
- A link is read under its row lock whenever there is one, the caller's
  own included; a first link that meets another's committed row on
  insert is `forge_unavailable`, not `installation_linked`, since that
  row may be the caller's own (A2545 #10).
- A claimed check writes nothing once the link's `checked_at` is no
  longer its claim's (`STALE`): a replacement's check that kept the
  link, or a relink, wrote a newer one meanwhile (A2545 #8).
- The check's write and a refused mint's run exempt from the calling
  request's write guard: they are the link human's writes, never the
  caller's, so a caller deleted, suspended or whose bridge ended
  meanwhile drops no `not_admin`; and the link human's `account_lock`
  comes first, as in an account's deletion, where the guard's check of
  a bridged call would take the project's lock before it (A2545 #2,
  §2.9's lock order).

**Reason:** with one timestamp, a refused mint or a check without an
answer would move the time a read rests on, and a link could serve on a
success older than 10 minutes (A2509 2a). The claim makes "at most every
10 minutes" hold across replicas and connections without a lock held
over forge calls, which can take seconds. A suspended link that minted
on every choice would call the forge more often than its cadence
(A2509 2b). Internal reasons keep a user account's reasons, which every
`project:admin` sees, from being shown for a link whose reasons depend
on the reader. A success at linking counted from the insert would, on a
replacement, come a whole check of the other link after the read it
rests on (A2544). Narrowing §11.3's check to such links keeps its answers
for every other project as they were (§11.3 had no `probe_not_configured`
before), which is the inferred part of this entry.

**Rejected alternatives:**
- A row lock held over the check's forge reads (`SELECT … FOR UPDATE`
  kept open across them): two engines would not both call the forge,
  but a slow forge would hold the link's row and every writer of it
  waiting for the whole check.
- A mint retry for a `suspended` link on its own throttle, as for a
  user account: a mint alone never sets it `active`, and a throttle from
  the suspension ends after the last success's 10 minutes anyway, so it
  would only add calls.
- Retrying a replacement whose link changed during its check: the change
  says another check or write is under way; the human links again.

## A page without sign-in counts only merges a read found public

**Id:** 6af0bb67-32dd-40df-91df-df1eb03288fc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §11.4 ("What a private repository's data may reach") and the event table, §8.2; the lead's decision on card tsk-dtpr7zqxhxc2, part 5b; the maintainer's answer to req-ds8mk5vdtkxx (old merges count); the maintainer's answer to req-tqf82hvzmnw3 ("ausnahme", the bare count may come from a grant's read)
**Revisit when:** another page without sign-in shows data the probe read, or the forge stops reporting visibility in the GraphQL read

`link_observed` carries `public`: whether the same GraphQL read reported the
repository public (`isPrivate: false`), `false` when it did not say; and
`read_via`: the source that read it. A page without sign-in counts merged pull
requests only from events with `public: true`, whichever source read them, and
only while the repository's last check found it public. Events without the field
do not count.

Changed on 2026-11-01: the count read only `link_observed`, which only a
card's forge link produces, while nearly all pull requests of a project
working with `maity report` are on reports: 4 of 712 cards had links, and a
public page showed 0 with over a thousand merges. It now also reads the ticker's
merge items, which carry `merge.public` (read with the instance's token, per
§11.4 no owner's grant), and only while the last check found the repository
public. Members' Overview counts every merge. Old items carry no flag and stay
uncounted on public pages; setting the flag on them is a data change that needs
no code, should the maintainer allow it. With nothing flagged the page has no
line: a 0 there says nothing was merged.

Changed on 2026-11-02: until then a link event read through a grant counted when the read found
the repository public, and the link events skipped the last check. Both went against §11.4. Events
already written with `public: true` can't be told apart by token, so they stopped counting at once
rather than running out of the 30-day window; that takes no data change, and few merges come from
links. A public project read only through an App or an owner's token has no line.

The ticker's `merge.public` is tested at the probe, since that flag is the only thing between a
read and a page without sign-in: a scan writes `true` only when its read reported the repository
public (`base.repo.private: false`), and `false` when it reported it private or did not say.

Changed on 2026-11-02, again: the maintainer decided that the old merges of named projects count
on public pages (req-ds8mk5vdtkxx). A one-time script, `hub/scripts/backfill_public_merges.py`,
sets `merge.public` on their ticker items and stamps each with `public_backfill`, so `--undo`
takes back exactly those. It is a script rather than a migration: the decision is about named
projects on one instance, a migration would run on every self-hosted one, and the project ids
don't belong in the repository. It refuses a project unless its id, name and repository address
all match and the last check found the repository public; it changes nothing without `--apply`.
The maintainer's §11.4 exception for the bare count (req-tqf82hvzmnw3) follows on its own card.

Changed on 2026-11-02, the third time: the maintainer made an exception in §11.4
(req-tqf82hvzmnw3). The bare number of merged pull requests may come from a read through the App
or an owner's token, as long as that read found the repository public; nothing else from such a
read reaches a page without sign-in, no title, no name, no link. The count no longer asks
`read_via`, and the ticker's scan sets `merge.public` from its own read's answer instead of from
the token; §17.2 of `docs/api.md` defines the field that way. A public project read only
through an App or an owner's token gets its line again, and link events read through a grant
while public count again; those were written with the read's answer all along.

**Reason:** §11.4 says data read through an owner's grant never appears
there, and the contract stands above this entry; privacy goes before the
statistic. Its one exception is the bare count read while the repository was
public, the maintainer's decision; inferred, not stated with it: a number of
merges in a repository anyone can read shows nothing that isn't public already. The read's own answer stays part of
the rule, or a repository that turned private between two reads would still
count. The old events go
uncounted on purpose: before the instance token was limited to public
repositories, it could read private ones too, so those events cannot
prove they were public. Privacy goes before the statistic.

**Rejected alternatives:**
- Counting only what the instance's token read (the rule on 2026-11-02 until the
  exception): a public project read only through an App or an owner's token had
  no line at all; the maintainer chose the exception.
- Letting more of a grant's read through while the repository is public, titles
  or links: §11.4 allows the bare number only.
- Counting events without the field: it may count merges of private
  repositories read before the instance token was limited.

## `probe_observed` wakes only when something on the pull request changed

**Id:** 07244da0-93d8-447e-a754-e143d8bbd536
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's adoption of the jour fixe of 2026-11-02 (round jfx-1fze3cfeq55h, req-658tp9mj77ny) on card tsk-m3w66pz16de9; the plan the lead approved on that card; docs/api.md §6.6 and the event table, §8.2
**Revisit when:** a reader needs `mergeable` settling from `unknown`, a release holder is woken twice by a recomputed conflict often enough to matter, or reports get a stored field for what was last announced

A report's observation wakes its readers only when `observed` (without its time)
or `mismatch` differs from what the card's last `probe_observed` to all of those
readers said. A new report starts with `observed: null`, so its first observation
is compared with the last one told, read from the card's latest `probe_observed`
events (redacted ones say nothing; one with an empty audience, or without the
current holder's token, told nobody now reading, as after a reassignment). A new
report the forge contradicts always wakes: its claimed head is news even when the
forge says what it said before. An observation that wakes nobody is still emitted,
with an empty audience: the owners' and admins' views read every event and
re-read the overview on it, and no agent is woken by it. On the open release, a ref is still stored and readiness rechecked
on every change, but announced only when `found`, `state`, `head_sha`, `checks`,
`merged_at`, `sha` changed, or the pull request started or stopped conflicting.

**Reason:** every waiting agent pays tokens for each wake. An agent that reports
again on the same head, or a pull request whose `mergeable` GitHub computes
lazily (`unknown` and `mergeable` take turns while nothing happens), woke the
holder and the admins with nothing to act on.

**Rejected alternatives:** a field on the report holding the last announced
observation: it changes the report's shape for every reader, while the event log
already holds what was announced. Leaving `mergeable` out of the release check
altogether: a pull request that starts conflicting is something the release
holder must act on. Skipping the event when nothing changed for the readers:
the views lose the report's new state until the next card event. Putting the
claimed heads into the comparison: a second report on the same wrong head would
then be compared with the first, while comparing the claim's mismatch alone says
what the holder must know.

Known and left for later: `unknown` counts as not conflicting, so a conflicting
pull request whose state GitHub recomputes (`conflicting`, `unknown`,
`conflicting`) wakes the release holder twice. Carrying the last known conflict
through `unknown` needs a stored value the observation does not have today.

## A forge answer is read within a size cap and one deadline for the whole body

**Id:** e8417295-6766-4952-ac7b-a103d8d7d4a2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-qtr9myhtysbs (hardening from the security rounds, tsk-v9kheekgq115), which asks for a byte cap and a total deadline "as `outbound._body` does"; the lead's security check of #1753's first version, which measured the trickle; the numbers are the coder's choice, not stated on the card
**Revisit when:** a real answer (a check-runs page, a large repository's metadata) comes near 16 MiB, or reads that time out at 10 seconds show up in the probe's log

Every request the hub makes to the forge's API, the probe's (`forge.Forge._send`)
and the GitHub App's (`github_app._open`), runs inside `forge.bounded`: a timer
shuts the sockets the request opened (`_Registering`) `READ_SECONDS` (10 s)
after it starts, so the connection, the headers and the body all end there.
The connection attempts themselves (`_connect`, in place of
`socket.create_connection`) each get at most the time left, so several
addresses together end at the deadline too; only the name's resolution
(`getaddrinfo`), which comes before any socket, is outside it. A
socket is held from the moment its TCP connection stands, and the TLS
handshake runs only after the TLS socket is held too, since wrapping takes the
descriptor from the TCP socket; holding and the deadline take one lock, so a
socket that comes after the deadline is shut as it is held. The timer shuts a
TLS socket through the plain socket's shutdown, which leaves the TLS object a
read in the other thread is using in place. The
body is read one recv at a time (`read1`), and a JSON answer past `ANSWER_CAP`
(16 MiB) is refused as `ForgeUnavailableError`, and so is a body that ends
before its declared length: a read with a byte count returns nothing there
rather than raising, and a cut JSON prefix can still parse. A raw file read
keeps its own cap (`raw_cap + 1`) under the same deadline.

**Reason:** before, `TIMEOUT` bounded each socket operation only, so an
answer that trickled a byte every few seconds kept the read, and the probe's
worker, open for as long as it liked, and `response.read()` took the whole
body into memory whatever its size. 16 MiB leaves room for a page of 100 check
runs with the forge's longest summaries; 10 s is what §11.1 sets for every
read the hub makes, "connect to last byte".

**Rejected alternatives:** a deadline checked between chunks, with each
recv's socket timeout cut to the time left (the PR's first version):
`HTTPResponse.read(n)` loops over recvs until it has `n` bytes, and each recv
that gets a byte before its timeout keeps it going, so a measured trickle of one
byte every 0.5 s held a 2-second deadline for 15 s; it did not cover the headers
either. Reusing `outbound._body` itself: it belongs to outbound's own
connection (pinned address, its `Refused` errors, gzip), while the forge reads
go through urllib's opener with the redirect guard.

## A fork's pull request is not compared with the project's branch of its name

**Id:** 141edd24-0c3c-413e-8efe-7e7e2761231c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-k0x4jn4y4ykg (delivery from a fork), the fix the lead approved through the coordinator, 2026-11-23; docs/api.md §6.6; `probe.observe_report`, `hub/tests/test_merged_closes.py`
**Revisit when:** a report says which repository its branch is in

When the probe has read the report's pull request and its head is in another
repository than the project's (`head_repo`, a fork), the branch of the
reported name in the project's repository is not compared with the report's
`remote_head`; `observed.branch_head_sha` still shows what that read found.
Before, a fork report beside a project branch of the same name was a
`mismatch`: the admins were woken, and the merge was never told to the done
authority. A report without a pull request read yet is still compared as
before, since nothing then says where its branch is. A renamed or
transferred project repository does not make its own pull request look like
a fork: `head_repo` is compared by name with the project's URL, reads at the
old URL stop at the forge's redirect until an admin sets the new URL
(`forge._SameHostOnly`), and setting it deletes the project's stored
observations (`routes/projects.py`). At most a read already under way then
is stored afterwards and, until it ages out, hides the branch comparison:
a missing signal, never a close, since `merged._not_its_own` counts such a
pull request as not the card's own.

**Reason:** the head repository the forge names on the pull request is the
one fact the hub already reads that says the branch is not the project's;
the change stays inside the probe, and every observation stored before the
hub kept `head_repo` is compared as before.

**Rejected alternatives:** a field on the report naming the repository the
branch was pushed to (the CLI reads it from the branch's remote): it would
cover a fork report before its pull request exists too, but needs a CLI
change, a contract field, a stored value and an answer for older CLIs that
do not send it, for a gap the pull request read already closes once there
is one (the rationale is the coder's reading; the lead approved the
narrower fix).
