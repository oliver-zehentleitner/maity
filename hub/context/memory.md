# Memory

## Memory caps count UTF-8 bytes and are checked under the project lock

**Id:** 2d7764da-8ff4-4d04-88c2-7c1eccd5b15b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §1.7 and §19.2 (an entry 2 KiB, the soul 8 KiB, a team and the community 64 KiB of live entries, `memory_full` instead of eviction); implementation session, 2026-10-23
**Revisit when:** the contract states the caps in characters, or a second replica writes memory (the lock is per database, so it still holds)

The caps are measured in bytes of UTF-8, not in characters: an entry is
refused above 2048 bytes, the soul above 8192. A team's, a role's or the
community's live text is summed from the rows before every write. The
write takes the project row lock first (`events.lock_project`). Two
agents of one team writing at once cannot both pass a check that only
one of them fits under.

**Reason:** "KiB" names a size. In characters the same cap would let a
text in a non-Latin script take up to four times the room. The sum is
read from the rows, not kept in a counter, because the stores are small:
64 KiB of live text is a few dozen rows. A counter would be one more
value that can drift from the rows it counts.

**Rejected alternatives:**
- Characters, as the request bodies' generic 16 KiB cap
  (`models.markdown`) counts them: too loose for the per-store totals,
  which exist to keep the resume packet and the stores small.
- A stored running total per store: needs the same lock to stay right,
  and adds a value to repair when it drifts.

## `q` filters memory in Python, not in SQL

**Id:** 0d8e8f4c-ffe0-465a-ac8e-b80519e60b45
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §19.2 (`q`: a case-insensitive substring of `text` or a tag); implementation session, 2026-10-23
**Revisit when:** a listing with `deleted=true` grows past what is reasonable to read whole, or the stores' caps rise

With `q`, `GET …/memory` reads the caller's readable entries, newest
first, and keeps those whose text or one of whose tags contains `q`,
case-folded, until the page is full. Without `q`, the page is cut in SQL
as usual.

**Reason:** a substring match inside a JSON list of tags, case-insensitive
in the same way on SQLite, PostgreSQL (JSONB) and MariaDB (JSON as text
under a binary collation), would need three dialect branches. The live
stores are capped at 64 KiB each, so reading them whole costs little.

**Rejected alternatives:**
- `LIKE` on a serialized `tags` column: under the binary collation
  MariaDB compares case-sensitively, and a tag could match across the
  JSON punctuation.
- A separate tag table: a join and a migration for a list of at most
  five words per entry.

## An agent's community entry is a proposal through the shared mechanism; only a `project:admin` human answers it

**Id:** 387e5443-ec34-4e96-9aa3-96faf8fcffb8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub owner's structure answer and the proposals PR (#230, with its answerer rule after review), 2026-10-23 (one `request.proposal` JSON column and a `proposals` module shared with the admin agent's member change); the coordinator's ruling in the review of #226, 2026-10-23 (the 202 in this PR; soul proposals after personal requests); the personal soul-proposal integration, 2026-10-25
**Revisit when:** team entries record their instance provenance, or the request answer rules gain a scope check of their own

An agent's `POST …/memory` with `store: "community"` answers `202` with
a `consent` request to `owner`. Its `proposal` is `{kind: "memory",
store, text, tags}`. `memory` registers that kind with an `Answerer` of
scope `project:admin`, humans only, which gates every answer (`go`, `no`,
text, talk), and with a `view`, so `GET …/requests/{id}` shows
`memory_proposal`. No event, list or resume packet carries it. Its
`settle` lives in `maity_hub/memory.py`, beside the domain rather than in
a route module. On `go` it stores the entry: the agent as `by`, its
session as when it asked, and the answering human as `confirmed_by`. A
store that filled up in the meantime refuses the go with `memory_full`,
and the answer rolls back.

A soul proposal now uses the same registry with kind `soul`, carried by a
personal request to `profile_owner:<agent id>`. Only its owner answers it,
through the personal routes, even without a project membership. The shared
personal guards keep it out of project lists and answers; its events carry
ids and status only. Settlement calls the existing versioned soul writer,
with the proposing agent as `by` and the human as `confirmed_by`. Its captured
`base_version` is advisory: §19.1 explicitly permits the owner to accept an
older proposal over a newer soul. Team entry instance provenance remains a
separate follow-up: `by.instance` is still null, with the session recorded.

**Reason:** a column and a settle hook per proposal kind would grow
apart with every feature that needs a human's go. The answer route lets
anyone with `requests:answer` answer a consent to `owner`, a proxy
included, but §19.2 gives the answer to `project:admin` alone. The rule
belongs to the kind, and the shared mechanism applies it to every answer. A soul
proposal must not use the community's project-owner addressing: that human
may be somebody else, while the profile's actual owner may be outside the
project. Reusing the personal request's guards avoids a second set of
privacy and withdrawal checks and needs no second proposal table.

**Rejected alternatives:**
- A `memory_proposal` column and a `memory.settle` call beside
  `placements.settle`: the second such pair, next to the admin agent's
  member change.
- `501 not_implemented` until the mechanism landed: not a code of the
  contract (§1.3), and the mechanism already existed as a consent to
  `owner`.
- A `project:admin` check inside `settle`, on `go` only: a proxy's `no`
  would still have closed the request.

## `changed_since_cursor` reads the memory events after the cursor

**Id:** 7e85719f-7bff-43ba-83dc-feaa01528730
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §19.3 (`changed_since_cursor`); the coordinator's review of #226, 2026-10-23 (the cost noted)
**Revisit when:** agents resume after long absences in projects with a busy memory, or a resume's memory block shows up in slow-query logs

The packet's `changed_since_cursor` reads the project's `memory_added`,
`memory_deleted` and `soul_changed` events with a `seq` after the
resume's cursor. It is true when one of them is the community's, names
the agent's team or current role, or is the agent's soul. The cost grows with the
memory history since the cursor, not with the project's events: the
`kind` filter runs on the indexed `(project_id, seq)` range.

**Reason:** no other record says when a store last changed. A stored
"changed at" per store would be one more value to keep in step with the
entries, and memory events are rare next to the rest of the log.

**Rejected alternatives:**
- A per-store `changed_seq` column, updated with every write: cheaper to
  read, but one more value that can drift from the rows it describes.

## Another team's agent gets `not_found` on a team entry, not `humans_only`

**Id:** 274d8b8a-aa2b-4fb0-a549-5f6f47312398
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the hub owner's structure review of #226, 2026-10-23 (the same point the coordinator made in the review of #224); the coordinator's ruling in the re-verification of #226, 2026-10-23, which aligned the §19.2 sentence (it had named `forbidden` with `humans_only`)
**Revisit when:** a role is given that reads other teams' memory without deleting it (then a refusal would no longer reveal anything)

`DELETE …/memory/{id}` on a team entry first checks whether the caller
reads that team. A caller who does not gets `not_found`, and that
includes every agent of another team, admin agents too. Only a readable
entry goes on to the rules for who may delete it.

**Reason:** "nobody else reads them" (§19.2). A `humans_only` refusal
would tell another team's agent that an entry with that id exists in a
team it cannot read. Every other project route answers what the caller
cannot see with `not_found` (§1.3). The effect the contract wants holds
either way: no agent deletes another team's memory.

## Role memory follows the named role, including a project's custom role

**Id:** 254f8287-0836-41d3-9e57-00c5abc728e7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.3 and §19.2–§19.3; card tsk-ysrb6pwqwhc6 and coordinating clarification, 2026-10-31
**See:** memory.md — 2d7764da-8ff4-4d04-88c2-7c1eccd5b15b — as of 2026-10-31
**Revisit when:** the contract changes role-memory ownership or proxy governance calls become available

Role entries belong to the project and the role's own name. Members
share that store, with its own 64 KiB live quota and 4 KiB resume block.
A membership changing roles reads the new store; existing entries stay
with the old role. Live entries prevent removing a custom role, while
tombstones retain its name as history without keeping the role in use.

**Reason:** §2.3 explicitly separates a custom role's memory from its
base's scope inheritance, and §19.2 makes entries the role's rather than
the author's. Reads and idempotent replays therefore check the current
role. Owner/admin members may read and manage other roles. A proxy is
excluded from that extra authority and retains its own role's coder
access; the coordinating clarification requires this boundary until
governance consent per call is implemented. General consent infrastructure
is outside this change.

**Rejected alternatives:** share a custom role's memory with its base,
which §2.3 excludes; grant foreign role memory solely from a proxy's
`admin` trust, which would let the interface act without its owner's
decision and was explicitly rejected in the clarification.

## A downgrade does not discard role-memory history

**Id:** 5e540987-9cc9-4fcd-84e9-e6a35df75159
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** role-memory schema migration and downgrade regression, 2026-10-31
**Revisit when:** an explicit export or retention policy defines how role history survives a downgrade

The role-store migration refuses a downgrade while any role entry,
including a tombstone, remains. An empty role store can downgrade;
existing team and community entries retain their previous shape.

**Reason:** the previous schema can represent neither the role store
nor its ownership name. Deleting those rows would silently erase live
knowledge or deletion history; assigning them to community or a team
would change their readers. Both were rejected in favor of a refusal
before altering the table.
