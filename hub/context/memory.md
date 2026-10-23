# Memory

## Memory caps count UTF-8 bytes and are checked under the project lock

**Id:** 2d7764da-8ff4-4d04-88c2-7c1eccd5b15b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §1.7 and §19.2 (an entry 2 KiB, the soul 8 KiB, a team and the community 64 KiB of live entries, `memory_full` instead of eviction); implementation session, 2026-10-23
**Revisit when:** the contract states the caps in characters, or a second replica writes memory (the lock is per database, so it still holds)

The caps are measured in bytes of UTF-8, not in characters: an entry is
refused above 2048 bytes, the soul above 8192. A team's or the
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

## Proposals go through the shared request mechanism; until it lands an agent's community write answers 501

**Id:** 387e5443-ec34-4e96-9aa3-96faf8fcffb8
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the hub owner's structure answer, 2026-10-23 (one `request.proposal` JSON column and a `proposals` module shared with the admin agent's member change, #139); the coordinator's order of work, 2026-10-23 (soul proposals after personal requests)
**Revisit when:** the `proposals` module is on main (wire the community proposal in), personal requests exist (wire `POST /me/soul/proposals` in), or agent instances exist (fill `by.instance`)

An agent's `POST …/memory` with `store: "community"` answers `501
not_implemented` for now, and `POST /me/soul/proposals` is not served
yet. Both become consent requests through the hub owner's `proposals`
module. It holds one `request.proposal` JSON column, a `register(kind,
settle, humans_only)`, and a `settle` call in the request answer and
withdraw paths. `memory` registers its own kind there and applies a `go`
from `maity_hub/memory.py`, the domain module beside the endpoints, so the
settle imports no route module.
Agent instances (§6.17) do not exist yet, so `by.instance` is null and an
entry records the session instead.

**Reason:** a column and a settle hook per proposal kind would grow
apart with every feature that needs a human's go. A soul proposal is a
personal request (§7), which the hub does not have yet. A 501 says
plainly that the call is not built. Refusing it as `humans_only` would
claim a rule the contract does not make.

**Rejected alternatives:**
- A `memory_proposal` column and a `memory.settle` call beside
  `placements.settle`: the second such pair, next to the admin agent's
  member change.
- Holding the PR until the proposal module and personal requests land:
  it blocks the stores, the soul and the resume block, which need
  neither.

## Another team's agent gets `not_found` on a team entry, not `humans_only`

**Id:** 274d8b8a-aa2b-4fb0-a549-5f6f47312398
**Type:** decision
**Status:** open
**Evidence:** confirmed
**Source:** the hub owner's structure review of #226, 2026-10-23 (the same point the coordinator made in the review of #224); docs/api.md §19.2, which names `forbidden` with `humans_only` for an admin agent deleting another team's memory
**Revisit when:** the contract owner rules on the §19.2 sentence (keep `not_found`, or answer `humans_only` after all)

`DELETE …/memory/{id}` on a team entry first checks whether the caller
reads that team. A caller who does not gets `not_found`, and that
includes every agent of another team, admin agents too. Only a readable
entry goes on to the rules for who may delete it.

**Reason:** "nobody else reads them" (§19.2). A `humans_only` refusal
would tell another team's agent that an entry with that id exists in a
team it cannot read. Every other project route answers what the caller
cannot see with `not_found` (§1.3). The effect the contract wants holds
either way: no agent deletes another team's memory.

**Open:** the contract's sentence says `humans_only` for this case. Until
the contract owner aligns the text or rules otherwise, the hub follows
§1.3, and the PR says so.
