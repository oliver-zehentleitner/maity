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
- A window or a column per isolation, so that events from the isolated time stay unreadable after a lift:
  the lead decided against it: the isolation prevents reading along while it holds, whoever lifts it trusts
  the agent again, and events with the audience `all` from that time are as readable for any new member; the
  effort buys no protection after a deliberate lift. The cursors move at the lift so that nothing is handed
  over by the next resume; an explicit `?after=` still reads the window.
- Reusing the pause: the contract gives isolation its own field, routes and effects (released claims, closed
  placements, no audience), none of which a pause has.

**Not covered:** the audiences of card events that name an isolated arbiter or assignee are not rewritten:
the agent reads none of them (`events.readable_by`), and a lift moves its sessions' cursors to the project's
head, so what happened meanwhile is not handed to it at the next resume; an explicit `GET …/events?after=`
older than the lift can still read the window, which was decided to stay so (below). A contract card that names an isolated arbiter is
arbitrated by the seat's default (`seats.routed_arbiter`), and the resume packet of an isolated agent carries
no request and no assigned card.
