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

## A runner caller is confined in one place, before any route runs

**Id:** 1d62b2f2-abdb-4470-91dd-8de0517f21b9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** runner design review with the coordinating agent, 2026-10-22

A runner credential (`docs/api.md` §15.1) authenticates like an agent's,
and right after authentication `deps._resolve` decides whether the path is
one a runner may call at all: `/runner/*` passes, a `/projects/*` path
answers `not_found`, everything else `forbidden`. `access.membership`
answers `not_found` for a runner as a second line, so a project route
never finds a membership for one.

**Reason:** about seventeen places branch on `caller.kind` as if there
were two kinds (`principal_id`, `access.membership`, the members,
requests and conversations routes): "not human" means agent, "not agent"
means human. A runner reaching any of them would be taken for the other
kind. Excluding it before the route runs makes those branches
unreachable for a runner, instead of correct only where someone
remembered to add a third case. Raising inside the authentication
transaction also undoes the call's last-use update, as the agent's
other-project refusal does.

**Rejected alternative:** a third case in every branch on `caller.kind`.
Each route would have to be right on its own, and a route added later
without the case would serve a runner as an agent or a human.

## An admin agent's members:admin is a path of its own, not the scope

**Id:** 1a2db596-5fb3-48b0-baa9-2cac8372cc3d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** contract #139 (`docs/api.md` §2.3 ᵃ) and the plan agreed with the contract owner, 2026-10-23

`members:admin` stays human-only in the scope table (`scopes.HUMAN_ONLY`),
so every `require("members:admin")` and `may("members:admin")` in the hub
still refuses an agent. `PATCH` and `DELETE …/members/<built-in function id>` take an
explicit path for an agent with the `admin` role (`maity_hub.admin_agents`).
It decides per target and field, and files a `member_change` proposal where
the owner's go is needed. Only the scope list in the resume packet shows
the limited scope (`scopes.listed_scopes`). The human-only refusals answer
`details.reason: humans_only` and are checked before the scope, so the
answer is the same for an agent of any role.

**Reason:** `members:admin` guards joins, runners, attachments,
placements, the member details and `spawn_consent_by`, more than twenty
checks. Granting the scope and narrowing it everywhere would open each
check that is missed; keeping it closed and opening two endpoints fails
closed.

**Rejected alternative:** granting `members:admin` to admin agents in the
scope table and adding a `kind == "agent"` refusal at every other use. The
table would then say more than the hub allows, and each new use of the
scope would have to remember the exception.

