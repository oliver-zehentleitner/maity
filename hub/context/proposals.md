# Proposals

Why changes that wait for a human's go (`docs/api.md` §2.3 ᵃ, §19.2) are built the
way they are. The mechanism is in `maity_hub/proposals.py`.

## One proposal column and a registry, not a column per kind

**Id:** a6278114-18bc-4e99-ba4d-a36045d72048
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the proposals scaffold (#230), 2026-10-23, for the admin agent (§2.3 ᵃ) and memory proposals (§19.2)

A consent request that applies a change on `go` carries it as JSON in
`request.proposal`, `{"kind": …}`. Each kind registers its settle
function, its answerer rule (a scope, humans only or not) and optionally
its own view fields. The request routes call `proposals.settle` on every
close and ask the rule before they accept or offer an answer. A kind the
hub does not know is never filed. When a stored one is unknown, an answer
to that request fails (`proposal_kind_unknown`), and lists and resume
packets leave it out. A close the hub makes itself, such as the
proposer's removal, withdraws it without its settle hook and says so in
the reason, so the removal does not roll back.

**Reason:** two slices needed the same thing in the same week, an admin
agent's membership change and a memory proposal, and more kinds are in
the contract. With a column, a branch in the answer route and an inbox
rule per kind, every new kind would touch the request code and its
migration.

**Rejected alternatives:**
- A column per kind, like `placement_id`. That needs a typed foreign key
  and a migration for every kind, and the routes still need a branch for
  each.
- `humans_only` as a single flag per kind. It cannot express §19.2,
  where only a human with `project:admin` answers, so a human proxy would
  pass.

## Placements keep their own settle path, beside the registry

**Id:** 0e868bf1-1026-4161-bd25-fd6f56d2532f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the proposals scaffold (#230), 2026-10-23
**Revisit when:** the placement code is next reworked, or a kind needs a state row of its own as placements do

A placement's consent is still linked by `request.placement_id` and
settled by `placements.settle`. The routes call both settle functions,
and each ignores requests that are not its own. A request carries one or
the other, never both.

**Reason:** a placement has its own row with a pending change, its own
refusal rule (`spawn_consent_by`) and re-checks on `go`. All of it is
tested, and it was in place before the registry. Moving it in the
scaffold would have rewritten working code in a pull request meant to
add a mechanism.

**Rejected alternative:** register placements as a kind right away. The
end state is cleaner, but a rework of the placement flow does not belong
in this pull request.

## A change that is no longer allowed refuses the go

**Id:** b1d249de-833d-4b34-80b0-b18699f4b05a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation of the proposals scaffold (#230), 2026-10-23, following `placements._still_allowed`

A kind's settle checks again on `go` whether the change is still allowed
(the target is still there, the rules still permit it). When it is not,
settle raises: the answer is refused and rolled back, and the request
stays open, so the human sees why and can answer `no`. A settle that has
nothing left to do, because the target was removed in the meantime,
returns without an error.

**Reason:** a request marked answered `go` whose change silently did not
happen tells the human something false. Refusing keeps the request and
the state in agreement, and placements already behave this way.

**Rejected alternative:** record the outcome (the answer stands, the
change is skipped, with a note). The human's answer would be kept, but
the request would then say `go` for something that never happened.

## Every kind treats `withdrawn` as a no-op or a clean-up: the addressee's withdrawal settles it

**Id:** f750b211-cee5-4ec7-9d64-625f21b8aaf3
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.26 (the invited human's withdrawal counts as their `no`), §7; the review of tsk-whe4wv1jpsae part 2, 2026-10-29
**Revisit when:** a kind has a side effect that must not run when the addressee takes the request back, or `POST /requests/{id}/withdraw` stops settling

`withdraw_personal` (`POST /requests/{id}/withdraw`, the addressee of a personal request) now runs
`proposals.settle` with the outcome `withdrawn`, as the project route and `close_request` always
did. Before, a personal request's withdrawal closed the row and nothing else, which was harmless
while no personal kind had anything to undo; an organisation's invitation does (its row stays
open otherwise). So a kind's `settle` must treat `withdrawn` as a no-op or as a clean-up of what the
request filed, never as an answer, and never raise on it: the addressee's withdrawal is the same
call as the hub's own close.

**Reason:** the withdrawal is a close like the others and a settle that is not told of it leaves
the thing it was filed for open (an invitation nobody can answer any more, still counted and
listed). The kinds that exist (`project_transfer`, `preferences`, takeovers, memory, the
admin-agent kind, `org_invitation`) were read and none does anything on `withdrawn` but close or ignore.

**Rejected alternatives:**
- Settling only for a kind that opts in: a kind that forgot to opt in would leave its row open,
  and that fails silently, which is what the rule is there against.
- Closing an invitation's row from the withdrawal route by hand: the route would then know a kind.
