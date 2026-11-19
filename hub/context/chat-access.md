# Chat access

## The firewall history is written from snapshots around each write of the lists, not from events

**Id:** 4b65c2c2-b020-484f-b430-ab0cdd707c6b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of docs/api.md §9.6 "History", card tsk-v34cv43wvec3, 2026-11-18; the account's deletion as one write is the lead's decision of the same day (seq 163796) on the contract, #1970
**Revisit when:** a write path of the lists appears that does not go through `chat_access` or `chat_gate.owner_yes`, or the lists start emitting events of their own
**See:** https://github.com/oliver-zehentleitner/maity — 756da7d0-c973-4ea0-82a0-5fe28a238f59 — as of 2026-11-18

`chat_access_history` gets its rows from the writes themselves:
`created` after an insert, and `watching` (or `before`/`after`)
around every write that may change or delete entries, which renders the
touched entries as the lists show them before and after and writes an
item per entry that differs. The cause rides a `ContextVar` set with
`caused` (an answer, an add, a deletion of what an entry names); without
one a write is the owner's own (`list`). An account's deletion runs
inside `one_write`, which keeps the first snapshot of each entry and
writes once at the end, skipping the leaving account's own entries,
whose history goes with it. The snapshots are taken under the entries'
row locks (a `PATCH` after its `FOR UPDATE`, a `DELETE` and
`forget_human` lock first), so "before" is the state the write changed.

**Reason:** comparing rendered views gives `fields` for free and stays
right when a write narrows through `_prune` or `_narrow_allows`, paths
that change agent rows without touching the entry's row. One snapshot
per logical write is what lets a deny that narrows an allow to no agent
and then deletes it show the agents it covered (#1970, A1340).

**Rejected alternatives:**
- Recording inside `_drop` and each `update`: a narrowing then a
  deletion in one write would give two items, the second with an empty
  `agents`, which the contract forbids.
- Deriving the items from events: the lists emit none beyond
  `chat_rules_changed`, an entry id for the agent alone.
- Passing the cause as a parameter through every function of
  `chat_access`: `forget_agent` and `forget_human` are reached from the
  profile and account deletions far away; a context variable reset in
  `finally` reaches them without changing those signatures.
