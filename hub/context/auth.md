# Authentication

## A call's side effects commit before the endpoint runs, in their own transaction

**Id:** d9800cc1-6d12-481a-a039-f389d758b11b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the authentication slice)

Resolving the caller (`maity_hub.auth.caller.authenticate`) and the side
effects every authenticated call has (`docs/api.md` §2.4) — `last_seen_at`
on the human, the membership, the session and the credential, the
renewal of the caller's leases, the move of its claims to the live
session — run in one transaction that commits before the endpoint's own
transaction starts.

**Reason:** presence and leases say that the caller is alive and working,
which is true whether or not the call itself succeeds: an agent whose
claim attempt answers `already_claimed`, or whose report is refused, has
still been heard from. In the endpoint's transaction an error would roll
the renewal back, and an agent that keeps hitting errors would lose its
leases while it works.

**Rejected alternative:** one transaction per request, side effects
included — one commit fewer per call, but a failed call would then erase
the evidence that the caller is alive.
