# Jour fixe

## Minutes online counted in a table of their own, one row per agent membership and minute

**Id:** a66f2814-0b24-4d78-a950-da07193ed882
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (jour fixe, part 1)
**Revisit when:** a second replica runs (both workers would count the same minute), or the table grows past what a day of agents online makes

The default moderator order (`docs/api.md` §20.2) ranks the admin agents
by their minutes online in the 24 hours before a round. The jour fixe
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
