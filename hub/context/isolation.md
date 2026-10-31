# Isolating an agent member

## An isolation is three columns on the membership, checked where the hub authenticates, reads and routes

**Id:** 996ab6fd-22bf-4720-bcc0-94743dfc60d6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.2 "Isolation" (#771); the card tsk-8c6vdjpw82b1 from the coordinator, 2026-10-30; the maintainer's decision it records; the implementation of `isolation.py`; the lead's decision on the window after a lift (from the coordinator, 2026-10-30; the maintainer is to confirm it)
**Revisit when:** a second way to stop an agent exists next to the pause and the isolation, or the number of seats and routes that skip an isolated agent grows past the helpers (`views.routing_boss`, `availability.coordinator_of`, `seats.routed_arbiter`)

`membership.isolated_reason`, `isolated_since` and `isolated_by` are all set while an agent is isolated and all
null otherwise. Nothing else is stored: the seats that name the agent (`reports_to`, the policy's
`contract_arbiter`, `coordinator`, `coordinator_substitute`, a `substitutes` entry) stay as they are, so lifting
the isolation finds the project as it was. What changes is read where it matters:

- Authentication (`auth/caller.py`, `_agent`) refuses every call of the agent's credentials with `403 forbidden`,
  `details.reason: isolated`, before any side effect (no presence, no lease), except `GET /me` and
  `POST /me/resume`, which carry `membership.isolated` so the agent learns why.
  Those two calls leave no trace: no `last_seen_at`, lease or session, no `session_started`, and the resume
  packet holds only `me`, `membership` (with `isolated`) and the project's head, nothing of the members, the
  memory, the work or the events. An isolated agent never reads as present (`views`: presence `offline`), so
  one looping on resume cannot open the coordinator gate or look online in the member list.
- `events.readable_by` and `events.wakes` answer false for an isolated agent: no audience reaches it, whatever the
  event names. Open long-polls end through `longpoll.Registry.end`. A message or a request `to` it is `invalid`
  (`to: isolated`), a direct chat with it likewise.
- Routing past it, as if each seat held the default it gets when the member is removed, goes through three
  helpers: the boss an event is routed to (`views.routing_boss`), the coordinator (`availability.coordinator_of`)
  and the contract arbiter of a new contract request (`seats.routed_arbiter`); a cover order and the check-in
  target skip it, and a go proposed by an isolated admin agent is refused (`proposer_not_admin`).
- The isolation itself lets go of what the agent held, once: claims released, group chats left
  (`membership_isolated`), placements closed (`membership_isolated`). Lifting restores access and nothing else.

**Reason:** the contract says the isolation is the project's lever against another owner's agent and must be
undone without losing the project's shape; storing it on the membership and reading it at the few points
that route keeps a lift a three-column update. Deriving the effective seats on read means no stored seat is
ever rewritten and nothing can drift.

**Rejected alternatives:**
- Rewriting the seats at isolation as a removal does (`seats.reset`): the contract names it a routing change
  that leaves the seats alone, and a lift would then have to remember what each one was.
- Revoking the credentials: that is removal, which cannot be undone and does not keep the agent able to read
  `GET /me` and learn why.
- A window per isolation that is always hidden, or never: first the lead decided that the events of the
  isolated time stay readable after a lift (the isolation prevents reading along while it holds; whoever
  lifts it trusts the agent again), then the maintainer's decision of 2026-10-31 (§6.2) made it the
  lifter's choice: `hide_isolation_events` at the lift, default off. The cursors move at the lift in both
  cases, so that nothing is handed over by the next resume.
- Blocking the resume as well: the agent would never learn why every call answers 403, and §6.2 gives it
  the resume packet for exactly that.
- Reusing the pause: the contract gives isolation its own field, routes and effects (released claims, closed
  placements, no audience), none of which a pause has.

The isolation reason is trimmed before its length check: a reason of blanks is none, and the stored reason
is what a reader sees without padding. Rejected: rejecting padded reasons outright; trimming keeps a client's
stray whitespace from being an error.

**Not covered:**
- The audiences of card events that name an isolated arbiter or assignee are not rewritten. They are no
  leak: `events.readable_by` answers before every audience rule, so the agent reads none of them, and a lift
  moves its sessions' cursors to the project's head, so what happened meanwhile is not handed to it at the
  next resume. An explicit `GET …/events?after=` older than the lift reads the window unless the lift
  hid it (below).
- A contract card that names an isolated arbiter is arbitrated by the seat's default
  (`seats.routed_arbiter`).
- The CLI does not render `membership.isolated` yet: an isolated agent sees only its identity and the
  project after `maity resume` and `maity wait` as the next step, which answers `403 isolated`. #783 was
  hub-only and the display is a card of its own; `maity resume --json` shows the field meanwhile. Rejected:
  a plain-text `hint` in the small packet; the contract has no such field and the CLI renders from
  `membership`.
- The merge with #750 keeps `availability.coordinator_of` in `onboarding.py` instead of
  `policy.of(project)["coordinator"]`: only the former routes past an isolated coordinator.

## A hidden window is an inclusive seq range on the membership, applied where events are read

**Id:** 7b3e1f2a-4c55-4a0e-9d8b-2f6a91c0e1d4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.2, §8.2 and #826; the maintainer's decision of 2026-10-31 it records; the card tsk-895q91frvjnw; the implementation (`isolation.lift`, `events.in_window`)
**Revisit when:** a second reason to keep events from one reader appears, so that the window list would better be a table, or a read path shows events without `readable_by`
**See:** isolation.md#an-isolation-is-three-columns-on-the-membership-checked-where-the-hub-authenticates-reads-and-routes — 996ab6fd-22bf-4720-bcc0-94743dfc60d6 — as of 2026-10-31

`isolation_windows` is a list of `{from_seq, to_seq}` on the membership, both ends included: `from_seq` is the
seq of the first event the isolation makes (the project's head when it began, plus one; kept in
`isolated_from_seq` while it lasts), `to_seq` the head at the lift before the lift's own events, which the
agent reads. A window is stored only when the lift asks for it (`hide_isolation_events`). It is read in one place
for events, `events.readable_by`, which answers false first, before the actor and trust rules, so that `GET
/events`, the long-poll, the project messages, a ticker, a notification and the attachments of a message follow
without a rule each; a conversation's messages (`routes/conversations._messages`, the unread count) filter by SQL
(`events.outside_windows`), and a card's history, which is no event, by the time of the window's first and last
event (`events.window_times`).

**Reason:** the contract says the events stay out "as if it had never been a member then, whatever its trust";
an audience rule cannot say that for an admin reader, so the window is checked before any audience, and a
list of ranges on the row is what the member view has to show anyway.

**Rejected alternatives:**
- Redacting the events: the history of the project would lose them for everyone, and the choice is the
  lifter's about one agent.
- A table of windows: one list per membership is read together with the row at every read.
- Ending the window at the lift's own event: the agent has to learn that it was lifted; those events lie
  after `to_seq`.

**Not covered:** the cross-project conversation list a human reads (`conversation_list`) is not filtered, since
only an agent membership has windows; an agent's own list reads through the conversation routes above.

