# Board

## Forge links are read in one GraphQL query per repository, only by the probe's worker

**Id:** 7acf0a83-0a4d-43e9-8be8-cf786c87d5e3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (card links), on the hub owner's review of the plan (no reads from a GET, mind the forge's rate limit)
**See:** https://github.com/oliver-zehentleitner/maity — e346b311-374d-4cf8-9468-23dd001c347a — as of 2026-10-23
**Revisit when:** a second forge is probed, or one project carries more forge links than a few GraphQL reads per round can cover

The probe's sweep, and a job the worker runs right after a link was
added, collect the forge links of each project that name the project's
own repository and read them in one GraphQL query per repository and 50
numbers (`issueOrPullRequest`), instead of one REST call per link. A link
on a closed card is read once more after it closed and never again. The
first observation of a link emits `link_observed` with `old: null`.

**Reason:** links multiply with cards; one REST read per link and round
would spend the operator's token's rate on titles nobody looks at, and a
read on a GET would make every board view wait on the forge. One query
per repository also asks the forge only about the repository the project
names, which is the rule that keeps the token's wider reach out of the
board.

**Rejected alternatives:**
- One REST read per link (`/issues/{n}`, `/pulls/{n}`): a request per
  link per round, and two endpoints to tell an issue from a pull request.
- Reading a link when the card is read: every board load would wait on
  the forge and could fail with it.

## A history entry names the event of its write, and a removed link lives on in the history

**Id:** 4f668fb7-2d60-48c8-b94b-03d537230015
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the edit history)
**See:** https://github.com/oliver-zehentleitner/maity — b780ee68-6e79-4b1f-b26a-67e7bb190989 — as of 2026-10-23
**Revisit when:** events are compacted or moved out of the database, or links need their own lifecycle beyond add and remove

Each history entry stores the `seq` of the `task_created` or
`task_updated` event its write emitted. Redacting the entry writes the
tombstone into its own `redaction` column, clears `before`, `after` and
`diff`, and replaces the same field's value in that one event. A removed
link's row is deleted; its history entries keep the link whole and name
it and the change (`link_id`, `link_change`: added or removed) in columns
of their own, so that a replayed add and a repeated `DELETE` find the
right entry — a link the card was created with has no add entry, only
the `created` one — and answer with the tombstone once it is redacted.

**Reason:** the contract redacts a value in the history and in the event
of the same write together. Storing the event's `seq` makes that one
lookup; the value never has to be searched for in the log. A deleted row
keeps the links table to what a card has now, and the history already
holds everything about what it had.

**Rejected alternatives:**
- Finding the event at redaction time by the entry id in its payload's
  `history`: a scan of the project's events, for every redaction.
- A soft-deleted link (`removed_at`): every read of a card would filter
  it, for data the history keeps anyway.

## A mirrored ships_with edge is history on the edited card only

**Id:** 2404ac29-1a96-45c7-b3d5-819512ea0efc
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (the edit history)
**Revisit when:** members ask why a partner card's history does not show the edge, or ships_with stops being mirrored

When a member sets `ships_with` on one card, the hub mirrors the edge on
the partner card. The member's card gets the history entry; the
partner's `task_updated` names `fields: ["ships_with"]` with
`history: []`.

**Reason:** the history records what a member changed; the mirror is the
hub keeping both cards consistent, like a rank or a request's block,
which the contract lists as events, not history.

**Rejected alternative:** an entry on both cards: two entries for one
decision, and the partner's would name an actor who never edited it.

## Subtask approval checks the resulting card, including an attachment

**Id:** 8a0dcd0b-7d35-41af-9d27-bce877e7bb44
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.1 and §6.4, the maintainer-approved subtask contract and its bypass rulings, 2026-10-25
**Revisit when:** subtasks can be opened by another path or the proposal policy changes
**See:** https://github.com/oliver-zehentleitner/maity — 60ddc489-48d5-4ac1-b93b-d3cb89581625 — as of 2026-10-25

Under `proposed`, a member without `tasks:admin` cannot create an open
child, open their own child proposal, or attach a non-proposed card. The
check sees the resulting parent and status together. Under `direct`, the
ordinary editing rules apply; clearing a parent stays free to the editor.

**Reason:** the proposal is the admin's oversight of new work on the board.
Checking creation alone would let a member open an ordinary card and then
attach it. Checking only the status transition would allow attachment and
opening in the same PATCH. The resulting state is the boundary in both cases.

**Rejected alternatives:** a creation-only check, or separate checks of the
old parent and old status. Both admit bypasses explicitly excluded by the
contract. Making every project require approval was also rejected by the
product decision: `direct` is the trusted-team option.

## Parent and dependency gates are checked together under the project lock

**Id:** bd484999-a651-42cd-88cd-a819a3ab5d8e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.4 and the subtask implementation design, 2026-10-25
**Revisit when:** cards move across projects or graph writes no longer share the project lock

Validation uses the resulting parent and dependency edges in one graph,
under the project's existing lock. A parent waits for its children, so its
implicit gate points from parent to child. Explicit dependencies point from
the waiting card to the card it needs. Depth and cycle checks use both.

**Reason:** checking only explicit dependencies misses a child waiting on
its own parent. Checking fields in sequence against old edges can reject a
valid combined detach-and-depend edit. Without the shared lock, two writes
could each pass against a graph that predates the other. These consequences
are inferred from the contract's final-graph and transaction requirements.

**Rejected alternatives:** independent dependency and tree checks, or
validating each field against the old graph. Neither sees the same graph
that will commit.
