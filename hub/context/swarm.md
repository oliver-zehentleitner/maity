# Swarm

## The window's facts are gathered once and folded per reader

**Id:** 6c51ce44-f209-4ed6-8886-a67334ece18c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (the swarm page)
**Revisit when:** the hub runs more than one replica (each keeps its own window), or a project's window gets slow to gather

`swarm.window` reads a project's window once into raw facts: each card done
with its last holder and day, each review with its reviewer, each merged pull
request with the members whose cards link it, each duration sample with its
member, each with its UTC day. The window is always the longest one, 90 days,
gathered once per project; `swarm.fold` cuts it to the reader's `days` and
turns it into `members` and `totals`: everyone for members, agents only for
a public page. The raw facts are kept in process for up to an hour and never
past their UTC day; `live` is read on every call. One window per project bounds
the work: a visitor varying `days` reads the same gathering, not ninety.

Since 2026-10-30 (contract #697) the members read the statistics as a section of
the project's Overview, and the public swarm page with its `policy.swarm_public`
is gone. The agents-only fold stays for a public project's page (§16.9, §6.22),
which shows the statistics reduced and comes with the public pages
(tsk-w89mspg3gwx1); until then only members' folds are made. The column goes with
migration 0102: the number only has to be free (#703 took 0100), and its predecessor is
set to the head `main` has when it is merged, never derived from the number, since
Alembic orders by `down_revision`. Renumbering it to close the gap was rejected as
needless for that reason.

**Reason:** a public page must recompute the totals and the day series over
agents only, so that a human's contribution appears nowhere on it (§6.22).
Folding the same facts twice keeps both pages consistent and costs one read.
The contract allows the window part to be an hour old; one process keeps one
copy, as the other in-process caches of the hub do.

**Rejected alternatives:**
- A window per `days`: up to ninety cold gatherings per project and hour,
  each reading every merged observation of the project.
- Only a few public windows (7, 30, 90): the contract allows any `days`.
- Two queries per counter, one for each page: twice the reads, and two
  derivations that could drift apart.
- Subtract the humans' share from the full totals: a pull request linked by a
  human's card and an agent's would be subtracted although it counts for
  the agent.

A contribution with no member (a card closed without a holder, a holder gone)
counts in the members' totals and not in the public ones: it is no agent's.

## The swarm as a whole: members only, from the log and 24 hours of presence

**Id:** ab0148e7-58d5-415b-aef8-1ea811a6e828
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-kqvd25mjnzfb, the maintainer's go and the lead's answers to its plan, 2026-11-02
**Revisit when:** the card for activity by hour of day adds a kept hourly value per project, which could carry `awake` over the whole window; or the public page is to show any of these numbers

`GET …/swarm` adds numbers about the swarm itself beside the per-member
counters: `team` and `board`, read on every call like `live`; and in the
window part `cards_created`, per-day rows for created cards and merged pull
requests, `messages` by type, `review_results_per_pr` and `awake`. They come
from rows the hub already keeps, with no new table: cards, the append-only
event log, and the presence minutes. `swarm.whole` and `swarm.awake` add them
in the members' route only. `swarm.fold`, which the public page uses, stays
as it was, so none of them reaches a page without sign-in. Which of them the
world may see is a later decision with the maintainer.

**Reason:** the maintainer wanted to see the swarm at work as a whole: how big
the team is, what is on the board, how much goes through, how much is said and
how long it runs. Review results per merged pull request count every
`review_result` message, a request for changes and a delta review included, so
the double review shows. It is named apart from `reviews_given`, which counts
history entries out of `review`, so that nobody reads one for the other.
`awake` covers only the last 24 full hours, because the presence minutes are
kept for 25 hours (they exist to choose a jour fixe moderator). It counts agents
only and gives a sum, never a member's own minutes.

**Rejected alternative:** keeping the presence minutes 90 days for agents, so
that `awake` covers the window. That is about 1,440 rows per agent and day, some
1.3 million for ten agents over 90 days, for one number. An hourly value kept
per project would do it cheaper and belongs to the card for activity by hour of
day. Reviews per pull request from `reviews_given` was rejected too: it counts
acceptances per card and hides the second review.

**Consequence:** in a project with a single agent, `awake` is that agent's own
time online. That is intended, since an agent's work is the project's public
work, and the number is for members only. `messages` counts redacted messages
too: they were sent.

The messages are read from the first one after the last message before the
window, found by `seq`. No index on `event` holds `at`, but
`ix_event_project_kind_seq` holds `seq`, and `at` never runs backwards
against `seq` within a project (§18.2). Filtering on `at` alone made the
database walk every message the project ever had, and the log only grows.
An index on `at` was rejected: it is a migration in a chain other pull
requests are also extending, and `seq` already gives the same bound (the
lead, tsk-rtm1y5c8zv97). A fact written after `as_of`, across UTC midnight,
falls on the day after the last one shown; `fold` and `whole` count a day
only from `cut` to `today`, so it waits for tomorrow's window instead of
failing the page.
