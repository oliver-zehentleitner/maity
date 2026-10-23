# Takeovers

## Time moves a takeover on in two places that settle alike

**Id:** 909c92a1-e1e1-49a4-822c-0a9706791a4e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.19), structure agreed with the hub's owner

An open takeover whose window ended is transferred (`window_elapsed`)
both lazily — every takeover call and every takeover open runs
`takeovers.settle` for its project first — and by a worker thread per
process (`takeovers.Worker`, like the image worker) that sweeps the
projects with due takeovers. Both call the same function under the
project lock, and the transfer is a conditional UPDATE on the status, so
the worker and a request, or two pods, never transfer one takeover
twice. The card routes never settle; a card read can show a takeover
whose window just ended until the next sweep.

**Reason:** a window ends without anybody calling, so a worker is
needed; the lazy path makes a call right after the window ended see the
result at once. The hub has no generic tick to hook into, and one was
not to be built for this alone.

**Rejected alternatives:**
- Only the worker — a holder's `accept` a second after the window ended
  would be refused or accepted depending on the sweep's timing.
- Settling on every card read — a write inside every read for a rare
  case.

## A takeover from an instance that is replaced or removed is cancelled, not carried over

**Id:** 152b59cd-7978-4268-ada4-e1aaa56ebeb1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-23 (`docs/api.md` §6.17, §6.19)

When a `replaces` exchange moves the held card to the new instance, an
open takeover whose `from` names the replaced instance is closed
`cancelled`. Removing a member cancels every open takeover in which it is
holder, receiver or requester. After any card write the card routes
call `takeovers.reconcile`: a takeover whose card no longer sits with
`from` is closed — `how: decided` when a human with `tasks:admin` moved
it, `cancelled` otherwise.

**Reason:** §6.19 cancels a takeover when the card stopped being held by
`from` "some other way" and names a replacement among the changes that
take a card from its holder. The requester learns of it through
`takeover_closed` and may open a new one against the new instance.

**Rejected alternatives:**
- Rewriting `from` to the new instance — the holder that was asked is
  gone, and the window it had would silently pass to an instance that
  never saw the request.
