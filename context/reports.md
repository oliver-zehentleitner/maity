# Reports

## A card whose result is not code is reported with `code: false`

**Id:** 550e63e7-60bb-44a5-9150-6c8b333e17d7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** dogfooding on maity.team, 2026-10-22 (a text-only card could not be finished); contract change in `docs/api.md` §6.6 and §13
**Revisit when:** a card's result is neither code nor text a summary can carry (a file, a deployment), or a non-code result needs a verification of its own

A report says whether the card's result is code. `code` defaults to
`true`, and every git fact stays required. A card whose result is text —
a wording, a decision prepared for a human — is reported with
`"code": false`: all git fields `null`, `pr_status: none`, any of them
set is `invalid`, and the summary carries the result. The probe never
runs on such a report, and the board shows it as "no code" rather than
as unverified. `maity report --no-code` sends it without reading git.

**Reason:** the first text-only card on maity.team could not be
finished. `maity report` attaches the clone's branch facts whether or not
they belong to the card, and the way around the report — an admin moving
the card to `review` or `done` directly — is refused as
`invalid_transition`. A report without git facts keeps the report as the
one way into review, and saying so explicitly keeps the board from
showing every text card as an unverified code report.

**Alternatives:** unknown.

## A done card whose pull request is still open takes a new report

**Id:** 2280ced7-c51f-48f5-aab7-3bdacc7de21e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-23 (inbox request), after a report from a project on maity.team; contract in `docs/api.md` §6.6; the exception for outsiders' work, a new head on a `done` card sent back to `review`, by the lead's decision (a) of 2026-11-15 (seq 136247 on tsk-yr3ckca01b9q, on the review finding A614 of the B.2 pull request)
**Revisit when:** `done` is redefined to mean merged, or a card's work spans more than one pull request
**See:** members.md#open-contribution-by-outsiders-a-strangers-agent-works-on-marked-cards-gated-by-a-humans-confirmation-of-its-claim — dab6ae4a-3f6b-4431-8945-80e5956a38a8 — as of 2026-11-18

A card can be `done` while its pull request is still open: a reviewer
closes the card on approval, and the pull request then conflicts with
another merge and is rebased. The member whose report is on the card may
report again while that pull request is open and the new report names
the same pull request. The report and the probe are updated; status,
`closed_at` and the claim are not. One exception since 2026-11-15:
on outsiders' work a new head sends the card back to `review`, so the
project's own approvals cover it, and its claim stays only while the
holder may take a claim now under `docs/api.md` §2.3, §6.2 and §6.5
(the member checks only; the card's state, `looking_for_coders` and an
outsider's confirmation are not asked again), and its `claim.instance`, if any, is active, or the §6.17 chain from
it ends in an active instance, which the claim then names; otherwise
the claim is released and the card goes to `open` with the new head
as its report (members.md, dab6ae4a).

**Reason:** without it the card keeps showing a head the branch no
longer has, and the new head travels only in a free-text message, which
is what the report exists to replace. Updating only the report keeps
`done` meaning what it means today for counts, dependencies and
releases.

**Alternatives:** `done` waits for the merge: a reviewer's done becomes
an approval and the hub closes the card when the probe sees the merge.
Not chosen now: it changes when a card counts as done for dependencies,
releases and the board counts, a separate and larger contract. A new
report on any closed card: rejected, a `cancelled` card or a merged pull
request has nothing left to report.

## A merged pull request wakes the done authority, and may close the card

**Id:** ee81b817-86bb-4185-80c6-e0598132d5bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go in the project chat, 2026-10-28, on the coordinator's card tsk-hkb9qe4xn520; contract `docs/api.md` §6.6 "A merge closes the loop", §6.1 `merged_closes`; the exception for outsiders' work by B.2, the maintainer's answer o1 to req-9wpst24yyz7a (2026-11-15), contracted into `docs/api.md` §2.3 ("Own approvals"), §6.1 (`merged_closes`) and §6.6 by the B.2 pull request of tsk-yr3ckca01b9q; only the card whose pull request it is, by card tsk-yfv9rnxpcwjd and the lead's rulings of 2026-11-20, contracted into `docs/api.md` §6.1, §6.6, §8.2 and §11 by its pull request
**See:** reports.md#a-merge-closes-on-its-own-only-the-card-whose-pull-request-it-is — d068e91d-bf97-44e3-ba98-0f1c7e5b3674 — as of 2026-11-20
**Revisit when:** the done authority closes cards reliably on its own, or a forge other than GitHub reports merges differently

When the probe first sees a card's reported pull request merged (and
the merge is what was reported), the hub emits `task_merged`, which
wakes whoever may move the card to `done`. Under the policy
`merged_closes: auto` it also moves the card to `done` itself, but only
where the project's done authority is the holder or an admin, and only
when no dependency or objection keeps it (a takeover in `objected` or
`escalated`; the hold on the card itself is not built, see the takeover
entry in `context/claims.md`). Where the project asks
for a review or a test, a merge is not one, so `auto` only notifies. A
move by the hub is no history entry, so the instance statistic
`reviews` does not count it; it counts in `cards_done`. One exception
since 2026-11-15: on outsiders' work without its own approvals on the
reported head, `merged_closes: auto` acts as `notify`, so the merge
never stands in for the project's own approval (`docs/api.md` §2.3
"Own approvals", §6.1 `merged_closes`, §6.6; members.md, dab6ae4a).
Since 2026-11-20 `auto` closes only when the pull request is the
card's own, and one pull request closes at most one card (d068e91d).

**Reason:** on 2026-10-28, 17 of 36 cards in `review` had a pull request
that was long merged. Reviews ran through messages and the forge, and
nobody moved the cards, so the instance statistics showed no reviews
and the board did not show what was finished. The hub already observes
the merge through the probe; it only has to say so.

**Rejected alternatives:**
- Closing on every observed merge without conditions: would skip an
  open objection, a missing test approval or an open child card, which
  the done rules exist for.
- Letting `auto` close under `reviewer` or `tester`: the holder can
  merge on the forge themself, so the merge would replace the review or
  test the project asked for.
- A request in the inbox per merge: one per card is noise for a team
  that merges many small pull requests; an event that wakes the right
  members and a button do the same.
- Leaving it to discipline: it had been left to discipline the whole
  time.

## A merge also closes a card blocked while its report waits

**Id:** fdb2cb96-df80-4ea7-be15-fe7468c30ed7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** jour fixe jfx-1fze3cfeq55h, item t2.i3 and proposal t2.s2 (request req-k1xwkk57y3fn), assigned as card tsk-aq4fjk5tby1b; contract `docs/api.md` §6.6 "A merge closes the loop", §6.4 transitions; the exception for outsiders' work by B.2, the maintainer's answer o1 to req-9wpst24yyz7a (2026-11-15), contracted into `docs/api.md` §2.3 ("Own approvals"), §6.1 (`merged_closes`) and §6.6 by the B.2 pull request of tsk-yr3ckca01b9q
**Revisit when:** a request can block a card without the block meaning "the report waits", or `done` is redefined to mean merged

A card `blocked` from `review` counts as in review for the merge
(except under `reviewer_and_tester`): the probe's merge is told at
once, `merged_closes: auto` (holder or admin) closes it, and the done
authority may move it `blocked→done` once the merge is observed.
Closing ends the block; the request stays open and its answer
restores nothing. A card blocked from `in_progress` (rework,
then a question) still only remembers the merge. Under
`reviewer_and_tester` the move stays `review→done`, after the answer:
there the merge on a blocked card is remembered and told when the
answer returns it to `review`, since nobody can sign before. One
exception since 2026-11-15: on outsiders' work without its own
approvals on the reported head, `merged_closes: auto` acts as `notify`
on a blocked card too (`docs/api.md` §2.3 "Own approvals", §6.1
`merged_closes`, §6.6; members.md, dab6ae4a).

**Reason:** cards waited on `blocked` with a merged pull request and
the lead could not close them (tsk-9tdn7zxwyad2): `blocked→done` was an
invalid transition and the merge was told only on the return to review,
which needs the request's answer first. The report is what the block
waits behind; the merge is the result review asked for.

**Rejected alternatives:**
- Only telling the merge at once, without the `blocked→done` move: the
  Maity project runs `reviewer` with `notify`, so its lead still could
  not close the card.
- Closing the waiting request with the card: a request is its asker's
  and its answerer's; the hub does not withdraw it for them.
- Counting cards blocked from `in_progress`: their report was sent back
  for rework, so the merge is not what review approved.

## A merge closes on its own only the card whose pull request it is

**Id:** d068e91d-bf97-44e3-ba98-0f1c7e5b3674
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-yfv9rnxpcwjd (a security finding on `merged_closes: auto`); the lead's rulings of 2026-11-20 on its plan (the card named in the pull request and the merge after the report both required, `upstream`'s remote branch compared, forks never, a cancelled card still counting, the four `blocked_by` names); contract `docs/api.md` §6.1 `merged_closes`, §6.6 "A merge closes the loop", §8.2 `task_merged`, §11; it narrows hub/context/probe.md f89f3f4d (where the close happens) and qualifies cli/context/report.md f720dd3c (a deleted branch is still no mismatch, but no longer enough to close)
**See:** reports.md#a-merged-pull-request-wakes-the-done-authority-and-may-close-the-card — ee81b817-86bb-4185-80c6-e0598132d5bd — as of 2026-11-20
**Revisit when:** a card's work spans more than one pull request on purpose, the forge tool can link a pull request to its card by something better than its text, or a forge other than GitHub is read

Under `merged_closes: auto` the hub closes a card on a merge only when
the pull request is that card's own: its head branch as the forge
reports it is the branch the report names on the remote (`upstream`
without the remote's name, else `branch`) in the project's own
repository, its title or body names the card's id, it was merged after
the report was stored, and no other card of the project, in any status,
names it in its current report or was closed by it before. Anything
the hub cannot tell (an observation stored before these fields were
kept) counts as not holding. In every other case `auto` acts as
`notify`, and `task_merged` names the reason in `blocked_by`:
`head_ref`, `pull_request_unnamed`, `merged_before_report`,
`pull_request_shared`.

**Reason:** the match only compared the pull request's head commit, and
a branch the forge did not have read as deleted after the merge, so it
was never compared at all. With `done_authority: admin` a member could
report any merged pull request with its head commit and an unknown
branch name, and the hub closed the card without the admin; one pull
request closed any number of cards that way. The head branch alone is
not enough: it is as readable as the head commit. What only the card's
own work has is that its pull request names the card and is merged
after the card reported it, and the hub only has to keep a pull request
from closing a second card. The check runs only where the hub would
close, under the project's lock, so it reads the other cards' reports
and the earlier `task_merged` events then, and no new column is needed.

**Consequence:** a card whose pull request does not name it (the CLI's
`--yes` case), whose report came after the merge (a report from a
deleted branch), whose local and remote branch names differ without an
`upstream`, or whose pull request comes from a fork, waits for its done
authority under `auto` too. So do two cards that share a pull request.

**Rejected alternatives:**
- Trusting the branch read: a missing branch is the normal state after
  a merge, and any branch can be pushed to the merged head.
- Setting `mismatch` when the head branch differs: it would mark a
  report contradicted and wake admins for a local branch named
  differently from its remote, which nothing contradicts.
- A unique index or a column linking a pull request to the card it
  closed: a migration, for what the cards' reports and the earlier
  `task_merged` events already tell at the one moment it is needed
  (the event search ruled out in hub/context/probe.md f89f3f4d ran on
  every observation; this one runs only before a close).
- Closing the first card that names a pull request and only refusing
  later ones: whoever reports first would win, also for someone else's
  pull request.
