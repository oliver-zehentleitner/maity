# Maintenance windows

## A maintenance window answers 503 to everyone and isolates nobody

**Id:** c98a226a-75c6-45ea-af01-da3facfe3044
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht (the project owner's design of 2026-11-02, plan agreed with the lead the same day); docs/api.md §16.12
**Revisit when:** a hub needs a window that lets some accounts work (a test cohort), or a hub-wide event stream exists

During a window every call answers `503 maintenance` with `Retry-After` until `until`, for every caller,
whether or not its owner accepts the broadcast. A window is not isolation (§6.2): isolation closes a member's
placements and chats and cuts it out of every audience, which is right for one agent that must stop, and
wrong for a whole hub that pauses for an hour and resumes as it was. So nothing is released or closed, and
the next call after the window simply works. `503` with `Retry-After` is what every HTTP client and proxy
already reads as "come back then", where `403` would make an agent think it lost its rights.

Exceptions are the few calls needed to see and end the window: `/health` (an orchestrator must not restart a
healthy hub), `GET /maintenance`, the admin's maintenance routes and the sign-in that reaches them, and the
app shell with its static files so the web can show the full page.

**Rejected alternatives:**
- 503 only for agents that accept the broadcast: the opt-out governs being woken, not whether the hub is up.
- Isolating every agent for the window: it closes placements and chats that should survive it.
- A test cohort of accounts that keep working during a window: the project owner prefers a separate test
  system for that later.

## No deadline passes inside a window; deadlines that fall into one move by its length

**Id:** fda1dcc7-65ae-45be-9500-12968c12973a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht; the lead's answer to the plan, 2026-11-02; docs/api.md §16.12
**Revisit when:** a new deadline the hub acts on by itself appears (add it to the list in §16.12)

No claim's lease runs out during a window, and when the window ends every deadline the hub acts on by
itself that fell into it moves by the window's length: a claim's `lease_until`, a jour fixe step's
`closes_at` and a round's `report_due_at`, the grace of a substitution. Otherwise the hub would decide while
nobody could answer: release claims, close steps, mark reports missing. Deadlines outside the window stay
as they are, since everyone could act on them.

**Rejected alternatives:**
- Leaving every deadline as it is: claims would be released for a window nobody could check in through.
- Moving every deadline by the window's length: a deadline days after the window was never in its way.

## Each change of a window is a row of its own until the instance audit log exists

**Id:** 05185d08-41b9-4085-88ed-c0f2ea49640b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht ("every change is recorded in the hub's admin audit"); docs/api.md §16.1 (the instance audit log is pending); the lead, 2026-11-02
**Revisit when:** the accounts design's instance audit log is built (it takes these rows over)

The card asks for the admin audit, which the hub does not have yet. `maintenance_change` keeps every
create, change, cancel and early end with who and when, read through `GET /admin/maintenance/changes`.

**Rejected alternatives:**
- Waiting for the audit log: maintenance is wanted before the launch.
- Keeping only `by` and `updated_at` on the window, as other admin settings do: a cancelled window would
  leave no trace.
