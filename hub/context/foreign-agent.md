# Another owner's agent

## A change of another owner's agent is one personal consent request that applies the whole change at go

**Id:** 0530e4cd-b339-4d49-8a0a-25f175f05dd1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.2 "Another owner's agent" (#771) and the maintainer's decision of 2026-10-30 it records; the card tsk-8c6vdjpw82b1 part 2 from the coordinator; the implementation of `foreign_agent.py`
**Revisit when:** a field outside `foreign_agent.FIELDS` becomes one an owner must agree to, or the agent's owner may name a delegate who answers for them
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-30

`foreign_agent.is_foreign` decides: the target is an agent and the caller's membership is neither its owner
nor an agent of that owner (`cross_owner.owner_of` on both), and the caller is not a manager acting inside its
reach (the `line:lead` path, which stays direct). Then `trust`, `role`, `areas`, `capabilities`, `briefing`,
`availability_policy` and `paused` of the `PATCH` are not applied: `foreign_agent.file` files one `consent`
request as a personal request to the owner (`to: human:<id>`, a proposal of kind `foreign_agent_change` that holds
the validated values and the pause), `asked_by` the caller, a summary with the current and the proposed value of
each field, and the answer is `202` with it. `settle` applies it at `go` through `apply_patch` as one
`member_updated`, the owner as approver and the caller as actor; a `no` or a withdrawal changes nothing. Other
fields of the same `PATCH` (`reports_to`) go their own way: at once, or the pair of #772. A further `PATCH` of the
member by such a caller withdraws the open request (`superseded`) and files a new one; removing the member
withdraws it (`member_removed`). An admin agent's change that needs a project owner's go (§2.3 ᵃ) is proposed as
before, and the owner's request is filed when that go is applied.

**Reason:** the contract makes an agent's settings its owner's to agree to, whoever has `members:admin` in the
project; reusing the personal request of #772 means an owner who is no member answers in the same place and the
project's routes stay closed to them. Storing the validated values in the proposal keeps `go` a plain apply
and puts the rules where they already run, on the call.

**Rejected alternatives:**
- A request in the project that the owner answers by the project route: a new access path into the project for
  an owner outside it, which #772 decided against for the same reason.
- Re-validating everything at `go` as the cross-owner edge does for cycle and depth: none of these fields can
  conflict with the project's state the way an edge can; a removed member is the only change that matters and
  withdraws the request.

At `go` the change is checked again as it stands now, not only the right to ask (`_still_allowed`): the
asker is still an active member, not isolated, and still holds `members:admin` (a human) or is still an admin
agent, by the role's base; the call's own rules hold against today's state (only an owner grants trust `owner`
or `admin` or the role `proxy`; an admin agent stays within §2.3 ᵃ, by `admin_agents.check_change`, the one
function its call runs too, so the two lists cannot drift); and the role is read again from the
project (`project_roles.base_of`), so a project role that was rebased while the request waited gives the agent
its base as it is now. A `go` that fails the asker's checks is refused with `409 asker_not_allowed`, one for a
role the project no longer has with `409 role_unknown`; either way the request stays open for a `no` or a
withdrawal, as every other refusal at a `go`. Rejected: not checking, as `cross_owner.settle` does for the
edge (there the asker's rights do not decide what the owners agreed to; here the asker's change is what is
applied). Rejected: withdrawing the request in the same call: the answer is the owner's and cannot be undone
from inside it. Rejected: counting an open request as a use of a project role: removing a role is then
refused by a request the owner may never answer; the `go` refuses instead.

A target that became a reviewer, a tester or the contract arbiter while the request waited would need the
project owner's go for an admin agent's change (§2.3 ᵃ); here the agent owner's `go` is the only consent asked,
decided so: it is the owner of that very agent who agrees to exactly the values shown.

**Not covered, and decided so:**
- The withdrawal of the request by anyone but the asker on the project route (the owner withdraws and
  answers under `/requests/{id}`); the contract gives no further rule.
- A caller with `members:admin` never takes the manager's path (`line_lead` is false for it), so a manager
  who also holds `members:admin` asks the agent's owner even for a member of its reach; only a `line:lead`
  caller without `members:admin` changes another owner's agent in its reach at once. Rejected: checking the
  reach for an admin caller too; the admin and the line paths stay apart as in §2.3.
