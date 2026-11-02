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
(password, link or code, and the second factor, since a signed-out admin with any of them must get in), the
two reads the sign-in page is drawn from (see the entry on them below), `GET
/me` read only (the web learns from it whether the viewer is the instance admin, who gets the button that
ends the window), and the app shell with its static files so the web can show the full page.

**Rejected alternatives:**
- 503 only for agents that accept the broadcast: the opt-out governs being woken, not whether the hub is up.
- Isolating every agent for the window: it closes placements and chats that should survive it.
- A test cohort of accounts that keep working during a window: the project owner prefers a separate test
  system for that later.

## The sign-in page's two reads stay open during a window

**Id:** 5a9a5806-3815-428d-8a75-a769af8e8cb5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-12hwmpykz2ht; the lead's decision after the review of the web part, 2026-11-02; docs/api.md §16.12
**See:** maintenance.md#a-maintenance-window-answers-503-to-everyone-and-isolates-nobody — c98a226a-75c6-45ea-af01-da3facfe3044 — as of 2026-11-02
**Revisit when:** the sign-in page reads anything else from the hub before the sign-in itself

`GET /auth/methods` (which ways to sign in this hub offers) and `GET /auth/pages/sign_in` (the admin's words
for the sign-in page) answer during a running window, for everyone; `GET /auth/pages/sign_up` does not, since
registration is refused then. Both are read only, carry nothing private, and the web draws the sign-in page
from them. Without them a signed-out instance admin, the one person the window must let in, met a sign-in
page that did not know whether to offer the mail link or the password.

**Rejected alternative:** keeping both refused and letting the web guess: the web PR did show the mail link
after a `503` on `/auth/methods`, but the page then offered ways the hub might not have and lacked the
admin's own words; a half-working sign-in page at the moment it matters most.

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
long the window really ran, and the hub moves the deadlines once, when the window is over: on the first request
or sweep after `until`, before any sweep acts on a deadline (a sweep on a quiet hub, or right after a restart,
would otherwise let a lease run out that was due to move), or at once on an early end; the sweeps that act on deadlines wait while it runs.

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

## Each replica trusts its last read of the window for 5 seconds; only the deadline sweeps wait

**Id:** b0bbdd1f-8166-44e4-905f-94f5e415081b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** PR #1204 (card tsk-12hwmpykz2ht) and its reviews of 2026-11-02; docs/api.md §16.12
**Revisit when:** a sweep acts on a deadline within seconds of it passing, or the hub keeps the window in a shared cache

The middleware asks for the window on every request, so each replica keeps its last read for 5 seconds
(`maintenance.CACHE_SECONDS`) instead of a query per request. A replica that has not read the window yet may
serve, or let a sweep act, for up to those 5 seconds into a running window. That is accepted: the sweeps run
once a minute or rarer, and no deadline is decided to the second. Past `until` the cache is not trusted: the
window is read again, which settles the deadlines first, so no sweep meets one that has not moved.

Only the sweeps that act on a deadline to someone's disadvantage wait during a window: availability, the
Keep the Why confirmation, the jour fixe, not listening and its hourly digest, organisation invitations,
registrations awaiting approval, and takeovers. The others keep running, since they decide nothing against
a person who could not act: the mail outbox and mailer, attachment and image clean-up, the forge probe, the
public pages renderer and the abuse report purge.

The legal pages stay readable during a window, with the banner, unlike the landing page and the public
project pages: an imprint and a privacy notice must be reachable at all times, and they change nothing.

**Rejected alternatives:**
- Reading the window from the database on every request: one more query on every call for a state that
  changes a few times a year.
- Pausing every background worker: mail and clean-up would pile up for the whole window for no one's benefit.
- Answering 503 on the legal pages too: the hub would be without an imprint for the length of the window.
