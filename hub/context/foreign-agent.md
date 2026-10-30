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

**Not covered:** the withdrawal of the request by anyone but the asker on the project route (the owner
withdraws and answers under `/requests/{id}`); the contract gives no further rule.
