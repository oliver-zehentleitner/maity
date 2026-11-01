# Jour fixe

## Minutes online counted in a table of their own, one row per agent membership and minute

**Id:** a66f2814-0b24-4d78-a950-da07193ed882
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (jour fixe, part 1)
**Revisit when:** a second replica runs (both workers would count the same minute), or the table grows past what a day of agents online makes

The moderator of a round (`docs/api.md` §20.2) is the member holding the
series' moderator right with the most minutes online in the 24 hours before
the round (until series existed: the admin agents of the project). The jour fixe
worker writes `presence_minute` (membership, minute) for every agent
membership with an instance online (§5.3: a call within 120 seconds or a
long-poll open; listening alone decides only whom a round reaches), at
most once per minute however often it runs, and deletes rows older than
25 hours. The order counts the rows of the last 24 hours. Nothing reads the table but the order, and no
response shows it.

**Reason:** the sessions keep only their current state, not the gaps
between them, so a sliding 24-hour window needs its own history. A row per
minute makes the window a plain count, survives a restart, and stays
small: at most 1500 rows per agent.

**Rejected alternatives:**
- Derive it from the session rows: a session's start and last call say
  nothing about the time it was not listening in between.
- A running total per membership: it cannot forget the minutes that slide
  out of the window.
- Online intervals (start, end) per membership: the same answer with
  overlap and clipping logic instead of a count.

## A round's thread opens with the round, and a pending further step waits in the steps list

**Id:** 9215f9e8-e417-43df-a815-6d8bd702808d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (jour fixe, part 2)
**Revisit when:** a round needs a thread it did not have from the start, or a second pending further step is allowed

This hub runs group chats, so every round runs in chat mode (`docs/api.md`
§20.5). The hub creates the round's thread when the round opens, with the
invited members, right after the round row so that the thread's view names
the round. A further step the moderator asks for is an entry in the round's
`steps` with `opened_at` null until it opens; when the exchange closes
first, the entry is dropped.

**Reason:** §20.7 defines the current participants as invited, active and
still in the thread. With the thread there from the start, that holds in
every phase: a member who leaves it during the answers is no participant of
the exchange either. The contract allows one pending further step at a time,
so one marked entry in the list the round already stores is enough.

**Rejected alternatives:**
- Create the thread with the statement: before it, participation would need
  a second definition, and a round without a statement would never get one.
- A column or table for the pending step: a migration for at most one value
  per round, which the steps list carries already.

## A round's thread and its messages wake nobody, told apart by the payload's jour_fixe marker

**Id:** b198fec1-37bb-4d0b-a6d4-7fe11a1800b4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (jour fixe, part 2)
**Revisit when:** a round's thread gets messages that should wake (the contract allows none today)

`events.wakes` returns false for a `message`, `conversation_created` or
`conversation_updated` whose payload carries `jour_fixe`: the statement,
the posts, and the thread's own open and close events. Each step wakes its
eligible members once, through `jour_fixe_step_opened`.

**Reason:** §20.5 counts every wake of a round: nothing else may wake anyone.
The thread's events are ordinary group-chat events addressed to the
participants by `member:`, which would wake each of them. The kinds are
shared with every other chat, so the kind alone cannot decide; the payload
already marks a round's message (§20.5) and the thread's view names its round.

**Rejected alternatives:**
- Add the kinds to `NON_WAKING`: it would silence every chat in the hub.
- Leave the participants out of the audience: they could no longer read
  their own thread.

## A proposal's decision request is asked by the moderator's membership

**Id:** 872ac41e-f165-4860-bbe3-ab63f1e35e58
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (jour fixe, part 3a)
**Revisit when:** requests get an asker that is the hub itself, or a human owner moderates rounds and files proposals to the owner

The hub files a `to_owner` proposal as an ordinary `decision` request
(`docs/api.md` §20.6, §7) with `asked_by` the moderator's membership, also
for a report the hub builds itself; `jour_fixe: {round_id, proposal_id}`
says where it came from.

**Reason:** every request has an asker (`asked_by` is not null), and every
reader of requests (the inbox, the views, the answer rules) relies on it. The
moderator is the member the round's triage stands for.

**Rejected alternatives:**
- A nullable `asked_by` for hub-filed requests: a migration and a null case
  in every request path, for requests that otherwise behave like any other.

A human owner who moderates and files a proposal to the owner asks
themselves, and a request is never answered by its asker; such a moderator
decides the proposal instead.

## An owner's later adopt opens the card; the final report stays as it was

**Id:** f92f24b6-1f63-4b70-86ea-5e822a586942
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (jour fixe, part 3a)
**Revisit when:** the report should show what became of its `to_owner` proposals

An `adopt` answer to a request filed for a proposal opens the card then,
with `created_by` the answerer and `jour_fixe` on it. The round's report,
final since it was filed, keeps that proposal's `task_id` null; the card's
`jour_fixe` and the request's link the two.

**Reason:** §20.6 makes a report final once written, changed only by
redaction. The request and the card already carry the round and the proposal.

**Rejected alternatives:**
- Write the card's id into the final report: a report that changes after it
  is final, and a second writer of it besides the moderator and redaction.

## A card still carries the hub's text while its title or body is exactly what the hub wrote

**Id:** b49bda1d-56e3-4435-93c1-c021ba596480
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-25 (jour fixe, part 3b)
**Revisit when:** a card opened from a proposal gets its text from somewhere else than the proposal

Redacting a report proposal rewrites the card an adoption opened only "while
the card still carries the hub's text" (`docs/api.md` §20.8). The hub
compares: the title is replaced when it still equals the proposal's title,
and the body when it still equals the body the hub wrote (the reason and the
round's line), which then becomes the same body with `[redacted]` for the
reason. A text a person has edited since, even by adding a line, is left as
it is. The card is found by
its `jour_fixe` mark, so a card opened by the owner's later adopt is reached
too.

**Reason:** the hub wrote exactly those values, and an edit by a person
changes them; equality answers the contract's question without remembering
anything.

**Rejected alternatives:**
- A flag on the card, set at creation and cleared by the first edit: a
  column and a write in every edit path for what a comparison already tells.
- The history's last title and body entries: an edit back to the hub's text
  would count as an edit, though the text is the proposal's again.
- The body starting with the reason: a person's added line would be
  rewritten with it.

## A report that names a statement proposal redacted before it arrived is refused

**Id:** b9b46e40-52be-47c6-8ae4-c57739f2683d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the reviewer's finding on the redaction pull request, 2026-10-27 (a redacted statement came back as a report proposal when the report arrived after the redaction); the choice between the two repairs the finding named is the implementer's
**Revisit when:** a moderator may legitimately carry a redacted proposal into the report, or the statement's redaction is recorded elsewhere than on the round's copy
**See:** jour-fixe.md#a-card-still-carries-the-hubs-text-while-its-title-or-body-is-exactly-what-the-hub-wrote — b49bda1d-56e3-4435-93c1-c021ba596480 — as of 2026-10-27

The redaction of a statement reaches the proposals and findings of a report
that already exists (§20.8). A report written after the redaction has no
such copy to reach: the moderator names `statement_proposal_id`, and the
hub took the title and reason from the report body itself. So a text the
maintainer had redacted could be filed again as a decision request. The hub
now refuses such a report: `invalid`, `details.fields.proposals:
"redacted_statement_proposal"`, checked on the round's copy, where the
statement proposal carries its `redaction`. Nothing is filed or opened and the
report stays due; a proposal of the moderator's own, with no
`statement_proposal_id`, goes through. The report the hub builds itself
already skips redacted topics and proposals.

**Reason:** the tombstone already sits on the round's copy, so one check
there closes the gap in the one place a report is accepted, and the
moderator learns at once why the proposal cannot be drawn from that source.

**Rejected alternatives:**
- Propagating the tombstone onto the new report before it is made final:
  the report would then file requests and cards that exist only as
  placeholders, work nobody asked for, and the moderator would not be told.
- Dropping the redacted proposal from the report silently: the moderator's
  report would differ from what was sent, without a word.

## A series keeps its schedule in the old policy's shape, and the upgrade writes its own event

**Id:** de0c97c0-a638-4c1a-9fb8-f14ab6d407a1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-31 (jour fixe series, card tsk-k1t68hg8eyxh, part 1 of 3); contract `docs/api.md` §20.1, §20.2 (#934, #936)
**See:** jour-fixe.md#minutes-online-counted-in-a-table-of-their-own-one-row-per-agent-membership-and-minute — a66f2814-0b24-4d78-a950-da07193ed882 — as of 2026-10-31
**Revisit when:** a schedule field needs a query or an index of its own, or memberships end through one function that could disable an owner's series at once

A series (`jour_fixe_series`) stores its schedule and windows as one JSON
`config` in the shape `policy.jour_fixe` had, with `enabled` a column of its
own; `jourfixe.schedule` reads it unchanged, so the slots, the DST handling
and the weekly interval did not move. The upgrade from the single schedule
runs in the migration whole, the `jour_fixe_series_changed` event and the
rules bump included, written as `rules.bump` writes them; only the consent
requests of the grants it leaves `pending` are not, the jour fixe sweep of
part 2 files them (8dcb08a3), and both parts deploy together. An owner's series
whose owner left is set to `enabled: false` by the jour fixe sweep (within
its 30 seconds) and refused at a manual start, not where the membership
ends. Report recipients are rows with a `receives` flag, so that a keeper who
takes itself off is a row as well (§20.2).

**Reason:** the schedule is only ever read whole by the slot logic, and the
contract keeps its fields as they were; a migration that writes its own event
needs no hub start that remembers what it still owes; and memberships end in
several places (removal, organisations, account deletion), while the sweep
sees every series every minute.

**Rejected alternatives:**
- A column per schedule field: schema churn for fields no query reads apart.
- The upgrade's event and rules bump at the hub's next start: a start-up task
  that must remember per project whether it ran.
- Disabling an owner's series where each membership ends: one missed path
  leaves a series running for an owner who left.


## The moderator right's two consents ride on consent requests, and the sweep ends rights and files what the upgrade owes

**Id:** 8dcb08a3-672d-48a2-816a-453bf27996c5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-31 (jour fixe series, card tsk-k1t68hg8eyxh, part 2 of 3); contract `docs/api.md` §20.2
**See:** jour-fixe.md#a-series-keeps-its-schedule-in-the-old-policys-shape-and-the-upgrade-writes-its-own-event — de0c97c0-a638-4c1a-9fb8-f14ab6d407a1 — as of 2026-10-31
**Revisit when:** memberships end through one function that could end their rights at once, or a third consent joins the two

A grant that misses a consent is a `pending` row of `jour_fixe_moderator`
and one `consent` request per missing side, carrying the proposal kind
`jour_fixe_moderator` (`proposals`): to the agent's owner in person (a
personal request, as a cross-owner `reports_to`'s, so an owner who is no
member finds it in their inbox), and to the keepers as `to: owner`, or for an
owner's series to its `circle_owner` in person. A `go` sets that side's flag
and the second makes the row `active`; a `no` or a withdrawal deletes the row
and withdraws the other request. The jour fixe sweep ends the rights whose
membership was removed or isolated or whose agent's owner left, withdrawing
their open requests, and files, on the agent's behalf (`filed_by: hub`), the
owner consents the upgrade left `pending` without a request. The minutes
online that pick the moderator now count humans online too (§20.2).

**Reason:** the proposal machinery already settles every close of a request
— answer, withdrawal, the hub's own — so a consent needs no route or column
of its own; and the sweep already visits every series each minute, which
reaches every way a membership ends, as for `circle_owner_gone` (de0c97c0).

**Rejected alternatives:**
- A table of consents beside the requests: a second record of what the
  request already holds, to keep in step.
- Filing the upgrade's consents in the migration: a migration cannot file
  requests with their events and records as the hub writes them.
- Ending rights in every place a membership ends: one missed path leaves a
  moderator who is no member.

## A round of an owner's series takes its readers from its own config, and the report list is read, not kept

**Id:** 10e772ac-0e65-449e-9fd3-8ba6a4976b56
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-31 (jour fixe series, card tsk-k1t68hg8eyxh, part 3 of 3); `to: member` confirmed by the team lead; contract `docs/api.md` §20.2, §20.5–§20.7, §20.9
**See:** jour-fixe.md#the-moderator-rights-two-consents-ride-on-consent-requests-and-the-sweep-ends-rights-and-files-what-the-upgrade-owes — 8dcb08a3-672d-48a2-816a-453bf27996c5 — as of 2026-10-31
**Revisit when:** a series' deletion stops leaving its rounds behind, or the request table allows a non-personal request to one human

Whether a member reads a round of an owner's series, and who its events,
thread and redactions reach, is decided from the round's `config` (its
`circle` and `circle_owner` as the round opened), never from the series row
(`jourfixe/circle.py`). The round's thread knows its `circle_owner` from the
round too (`group_chats.round_keepers`), and is told it at creation, before
the round points at its thread. Its events also escape the owners' and admins'
see-all (§8.2): the batch's reading marks them `circle:<seq>` (from the
round's `config`, or the series row for a series event), and only their
audience reads them. A series event of an owner's series that was since
deleted is no longer found and falls back to the see-all; it carries no
topic, and the admins are in its audience anyway. In such a thread, owning
the moderator agent does not bring its owner in either (`outside:<chat>`).
The round points at its thread before `conversation_created` is written, so
that event names the round and its observers. The report list may hold a
moderator of the series (§20.2), but a round's report goes only to those
who read that round (§20.7): a moderator reads the rounds it moderated. A `to_owner` proposal goes to the
`circle_owner` as `to: member` while they are a member, and as a personal
request once they left. The rounds list leaves out what the caller may not
read by reading on in batches until the page is full. The report list
(`jour_fixe_recipient`) stores only what differs from the default — a member
on it, a keeper off it — and who receives a report is worked out when it is
read: the keepers and the listed, each only while it reads the series'
rounds; the human recipient's inbox item is derived the same way. The report
wakes only the agent recipients' selected instances; a skip and a series
change wake nobody.

**Reason:** a deleted series' running round runs to its end (§20.1) with no
series row left, so only the round can still name its owner. The request
table holds a request to one named human only as a personal one, while §20.6
asks for a personal request only once the owner left, and a member is
reachable as `to: member` (the check `ck_request_personal_shape` allows
`to_kind: human` only together with `personal`; the team lead confirmed
`to: member` for a member, 2026-10-31). Reading the list rather than pruning it covers
every way a member stops reading the rounds — leaving, a moderator right
that ends — without a hook in each.

**Rejected alternatives:**
- Looking the series up from the round: gone once the series is deleted.
- Filtering the rounds list after the page is cut: short pages, and a
  cursor that skips rounds.
- Deleting list rows wherever reading ends: one missed path leaves a
  recipient who may not read the report.
