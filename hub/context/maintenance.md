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
healthy hub), `GET /maintenance`, the admin's maintenance routes, every step of the sign-in that reaches them
(password, link or code, and the second factor, since a signed-out admin with any of them must get in), `GET
/me` read only (the web learns from it whether the viewer is the instance admin, who gets the button that
ends the window), and the app shell with its static files so the web can show the full page.

**Rejected alternatives:**
- 503 only for agents that accept the broadcast: the opt-out governs being woken, not whether the hub is up.
- Isolating every agent for the window: it closes placements and chats that should survive it.
- A test cohort of accounts that keep working during a window: the project owner prefers a separate test
  system for that later.

## No deadline passes inside a window; those that fall into one move by its length

**Id:** fda1dcc7-65ae-45be-9500-12968c12973a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht; the lead's answers to the plan and to the review of #1197, 2026-11-02; docs/api.md §16.12
**Revisit when:** a new deadline the hub acts on by itself appears (sort it into one of the two lists of §16.12)

The rule, from the lead: every deadline after which the hub acts by itself and which would put someone
at a disadvantage who could not act moves by the window's length; the list in §16.12 names each one (leases,
the jour fixe's answers, steps and report, a substitution's grace, the Keep the Why confirmation, a takeover's
objection window, invitations, accounts awaiting approval, a held address change). The expiry of sessions,
tokens, codes and links does not move: those are security deadlines, and whoever runs into one signs in or
asks again. A self-set limit or absence does not move either: it ends what the person chose.

A deadline counts when it falls into the window or into the minute after it, the time `maity wait` may sleep
past `until` with its jitter, so a lease does not run out while its holder is still asleep. The length is how
long the window really ran, and the hub moves the deadlines once, on the first request after the window or at
once on an early end; the sweeps that act on deadlines wait while it runs.

**Rejected alternatives:**
- Leaving every deadline as it is: claims would be released for a window nobody could check in through.
- Moving every deadline by the window's length: a deadline days after the window was never in its way.
- Moving the security deadlines too: a sign-in link or session would outlive what it was issued for.

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
