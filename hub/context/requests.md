# Requests

## A personal request is a request row with the asker's project, hidden from every project route but the asker's

**Id:** a753a0f6-a606-43dd-86db-3431a1679721
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** docs/api.md §7 ("Personal requests"); the hub owner's review of the schema plan, 2026-10-23 (no classification without a CHECK, `project_id` written down, `to_human` as a snapshot); implementation session, 2026-10-23
**Revisit when:** a personal request is filed that belongs to no project, profiles change hands while requests are open (§6.19 takeovers of a profile), or human notifications (§18) need their own record of it

A personal request is an ordinary `request` row with:

- `to_kind: "profile_owner"`, the profile in `to_profile` and its owner at filing time in
  `to_human`;
- `personal` true, tied to that `to_kind` by a CHECK (`personal_shape`), so no row is
  half one and half the other;
- `project_id` as the asking agent's project.

The project's request routes treat it as absent for everyone but the asker:

- the listing filters `personal = false`;
- `GET` answers only the asker; the asker's `answer` is `self_answer`;
- everything else, and every `withdraw`, is `not_found`;
- `inbox.may_answer` is false, which keeps it out of an admin agent's `to_answer` in the
  resume packet.

The human reads, answers and withdraws it through `/requests/{id}`, member of the
project or not. A non-member's answer has `answered_by` null and `answer.by` set to the
human's id. Its events carry `{id, personal, status}` only, to the asker plus the owner
when the owner is a member. It never becomes a card's `blocked_by_request`: every reader
of the card would see its id, and the card would wait on a human who may not be in the
project. A non-member's answer resolves no mentions, since resolving would hand an
outsider the members' ids (§6.2). An agent on `/requests/{id}` gets `humans_only` (§2.3).

**Reason:**
- One table keeps a personal request on the paths every request already has: the
  asker's resume, its `GET`, blocking and unblocking a card, the hub's own
  `close_request`.
- Keeping the asker's project means none of those paths needs a "no project" branch.
  `project_id` stays NOT NULL.
- `to_human` is a snapshot. The request asks the human who owned the profile when it was
  filed, and a later change of owner does not move an open request to someone who was
  never asked.

**Rejected alternatives:**
- A table of its own: a second set of answer, withdraw and event code for the same
  lifecycle.
- A nullable `project_id` for requests outside a project: every project query would need
  a `project_id IS NOT NULL` guard. Today every personal request belongs to an agent's
  project, the soul proposal and the takeover notice included.
- `personal` derived from `to_kind` alone, without the column: the hub filters on it in
  every project listing, and a boolean says that in one word. The CHECK keeps the two
  from disagreeing.

## A question blocks its card only when it says it waits; `while_open`'s default follows the class

**Id:** 3d44b07f-3ab6-41be-8bd0-a799eb11c530
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** jour fixe 2026-11-02, proposal r4 (a question to the human set the card to `blocked`, and the lead could then not set it to `done` after the merge, while often only a side question was open); card tsk-qr32egwhrxz1 and its plan note, approved by the lead, 2026-11-08
**Revisit when:** a request needs to block a card without the asker holding it, or `_unblock` needs to tell blocking requests from waiting ones that blocked nothing

A request without `while_open` takes the class's default:

- `wait` for a `consent`, which may not be anything else (§7);
- `proceed_provisionally` for every other class.

Only `wait`, given or a consent's default, blocks the card the asker holds; the remembered
status and the restore on the last answer stay as they were. `maity ask --wait` sends
`while_open: wait`; without it the CLI sends none.

**Reason:**
- `maity ask` never sent `while_open`, so every `ask --task` blocked the card under the old
  default `wait`, a side question included.
- `while_open` already says what the asker does meanwhile, and the inbox shows that to the
  human; a default of `proceed_provisionally` makes it say what is now true.
- A consent asks "may I", so the asker cannot go on without the answer; it keeps waiting.

**Rejected alternatives:**
- A separate `block` field: `_unblock` counts the other waiting requests on the card, so
  it would need a stored column, a migration and a slot in the migration order.
- No automatic block, the asker setting `blocked` by hand: no status transition leads
  there, and the restore on answer would be lost.
- `proceed_provisionally` for every class: a consent must wait, and its validation
  (`consent_waits`) would refuse every bare consent.

## A request listing sorts and pages light entries and builds full views only for its page

**Id:** 1a0b7116-3d75-451f-9b49-fcdad7cdeead
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the inbox card tsk-430dnt8s25a8 (the maintainer's report that the inbox loads for seconds), measured on a local fixture before and after, 2026-10-29
**See:** notifications.md#deriving-items-reads-each-kind-of-lookup-once-per-batch-not-once-per-event — b4a7c2f0-e8c8-4e9d-a093-95f07b4eb411 — as of 2026-10-29
**Revisit when:** a sort key needs a field of the full view, or a listing must answer more than a page at once

`GET …/requests` and `GET /requests` filter their rows, then turn each into a light
entry (`_entries`): its id, priority, stored timestamp and the asker's handle, the handles
read for all rows in two queries. Sorting and keyset paging work on those entries; only
the entries on the page become full views (`request_view`, through `_page`'s `render`).
The cursor is unchanged, since it only ever carried those fields.

**Reason:** a full view costs several queries (asker, addressee, holder, card, avatar,
placement), and the listings built one for every filtered row before cutting the page. So
the cost grew with every request a human ever had, history included (`status=all`), not
with what the page shows. On a local fixture of 120 requests the project list went from
857 queries and ~155 ms to 269 and ~55 ms, and stays at that count for 60 or 120; on a
server database each query is a round trip, which is where the seconds came from. A test
keeps the count flat as requests grow.

**Rejected alternatives:**
- Batching every lookup of `request_view` for a list: the view reads from many helpers
  that events and single reads share, so a batched variant would be a second form of the
  same view that has to agree with it, for a cost that the page already bounds.
- Paging in SQL: the `agent` sort orders by the asker's handle and the filters
  (`to=me`, `may_read`) are decided in Python, so the database cannot cut the page alone.

## An instance address in `to` is stored as written, resolved when each event is written; the asking instance is never stored

**Id:** 94c76ded-719a-4455-92c6-065964e3dae7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract owner's answer to the implementation question, 2026-10-30 (docs/api.md §7 `to`, §8.2 request events, §6.17; no `asked_instance`, no migration for the asker)
**Revisit when:** a request's addressed instance has to be shown by its current successor, or sessions and credentials start to be deleted

`request.to_instance` holds the instance id of `to: <member>#<id>` exactly as written. The view shows `to` from it (`<member>#<id>`), and the audience of `request_created` (also on a forward or withdrawal, which rebuild it from the row) is resolved again by `instances.addressed` each time an event is written: the named instance, else the instance that replaced it along the chain, else (revoked, no successor) its own token, so the write is accepted and wakes nobody. An id the member never had is `invalid` (`to: not_an_instance`).

The asking instance is not stored. `asked_by.instance` and the audience of `request_answered` and `request_withdrawn` take it from the credential of `asked_session_id`, which the hub never deletes. A human asker, an asker with no session and a hub notice (`filed_by: "hub"`, which reaches the addressed owner only) keep `member:`. A proposal's `Settlement.proposer` carries that credential, so a settled change names the instance that asked.

**Reason:** the address is a fact about what the caller wrote and the successor is a fact about when the event is written: storing the resolved token would show a request to a successor the caller never named and would go stale at the next replacement. The asker needs no column because the session already says which credential filed it.

**Rejected alternatives:**
- An `asked_instance` column (the card's first idea) — a second copy of what `asked_session_id` already derives, with nothing it could answer that the derivation cannot.
- Storing the resolved token in `to_instance` — loses the address as written (§8.2 keeps `payload.to` as written) and fixes the successor at filing time.
- Moving a message's and a mention's address onto the same chain resolution in the same change — not part of that card; it followed as tsk-q7p3sz8df62q (`hub/context/instances.md`, f1486a50-2c5b-4f56-b19a-e57e2ce6ce4e).

The list filter `GET …/requests?to=<member id>` matches a request addressed to that member
and also one addressed to an instance of its team: the team reads the instance addresses, so a
plain member id names them too (the coordinator's decision, 2026-10-30, on spq4's review of
the instance-address change). `to=<member>#<id>` matches that address only, as written.
