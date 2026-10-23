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
hub does not know is never filed. When a stored one is unknown, only that
request fails (`proposal_kind_unknown`); lists and resume packets leave
it out.

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
