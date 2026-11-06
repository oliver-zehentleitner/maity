# Another owner's agent

## A change of another owner's agent waits for that owner, and a reports_to inside that owner waits with it

**Id:** e201515c-83ac-4d96-863e-b30c6c03da96
**Type:** decision
**Status:** active
**Evidence:** inferred
**Verification:** corroborated — the implementation matches this entry (`foreign_agent.py`, `jcs.py`, the member PATCH)
**Source:** docs/api.md §6.2 "Another owner's agent" and "Across owners", the maintainer's decisions of 2026-10-30 and 2026-11-04 recorded there; the implementation
**Revisit when:** a field outside the consent's list becomes one an owner must agree to, or the go's refusal codes are named differently
**See:** manager.md#a-cross-owner-reports_to-is-a-pair-of-personal-consent-requests-that-set-the-edge-at-the-last-go — 5d9be0ad-ef77-487e-b95a-1cf9ea2674d4 — as of 2026-10-30

`foreign_agent.is_foreign` decides: the target is an agent and the caller's membership is neither its owner
nor an agent of that owner, and the caller is not a manager acting inside its reach (the `line:lead` path,
which stays direct). Then `trust`, `role`, `areas`, `capabilities`, `briefing`, `paused`,
`availability_policy` and `dormant` are not applied on the call, and neither is a `reports_to` that stays
inside the agent's owner (`null`, that human, or another agent of that human). One `consent` request goes to
the owner (`to: human:<id>`, kind `foreign_agent_change`), `asked_by` the caller, holding the validated
values, the pause and a SHA-256 of each value's canonical form. The answer is `202`. `settle` applies the
stored values at `go` as one `member_updated`, the owner as approver and the caller as actor. A `no` or a
withdrawal changes nothing. A further `PATCH` by such a caller withdraws the open request (`superseded`) and
files a new one; removing the member withdraws it (`member_removed`). An admin agent's change that needs a
project owner's go (§2.3 ᵃ) is proposed as before, and the owner's request is filed when that go is applied.

A `reports_to` that crosses owners stays the two-owner pair and is not also a field of this request: the
subordinate's owner is already one of the two who consent, so no second request is filed on top of the pair.
When the same `PATCH` files both, the `202` lists the pair's ids as `cross_owner_reports_to` (the boss's
side, then the other when two are filed). That list is on that answer only. A replay of the same `PATCH`
returns the same ids, through the loader of that answer (`member_patch`). A later read of the request, and
a replay of the owner's answer, do not carry it; the pair is read by those ids.

The number and string tokens of that change are read from the raw body before a model does, and only when
the change waits for the owner. A fraction or an exponent (`1.5`, `1e20`, `1e5`, `-2e1`), an integer
outside the range the canonical form allows, and `1` or `0` where the field is a boolean (`dormant`), are
`invalid` with `not_an_integer` on the field itself. A lone surrogate, `dormant` included, is
`lone_surrogate`. A change the caller applies at once keeps the model's own error.

At `go` the change is checked again as it stands now. The asker is still an active member, not isolated,
and still allowed to make this change, else `409 asker_not_allowed`. A project role the project no longer
has is `409 role_unknown`, and its base is read again. A stored `reports_to` is one of the call's own
rules against the members as they are now: a missing member, a guest, a cycle or the depth is the same
`409 asker_not_allowed`, and the request stays open for a `no` or a withdrawal. The cross-owner pair's own
go keeps its `400` (`cycle` and the rest); that paragraph names them, and this request is not that pair.

**Reason:** an agent's settings are its owner's to agree to, whoever has `members:admin`; the personal
request is where an owner who is no member already answers, and the project's routes stay closed to them.
Folding a `reports_to` that stays inside the owner into the same request means the owner agrees to the
whole change, not to the other fields while the edge moves on its own. The pair's ids belong to the call
that filed both, so they ride on that answer and not on every later outcome of the request. The canonical
form stores an integer, and `1.0` is not `1`; the model's int and bool readers would hide the token, so
the check runs first, and only for a change that stores one. The go paragraph names two refusals, and the
call's other rules already become `asker_not_allowed`; a `reports_to` that no longer holds is one of
those rules. The half of this that the contract states outright is the behaviour of the request, the
pair and the tokens. That a missing member or a cycle on this go is `asker_not_allowed`, rather than a
code the paragraph does not name, is the reading of "the call's own rules".

**Rejected alternatives:**
- A request in the project that the owner answers by the project route: a new access path into the project
  for an owner outside it, which the cross-owner edge decided against for the same reason.
- Sending a `reports_to` that stays inside the owner its own way, at once or as a second request: the
  owner would agree to part of the change and find the edge already set.
- One loader for every outcome of a request, so a replay of the answer carried `cross_owner_reports_to`.
  The list is not part of the request; it is part of the answer that filed the pair.
- Checking number tokens on every member `PATCH`. A change applied at once is not stored as a canonical
  value, and its error would move for no stored form.
- Applying a stored `reports_to` that no longer names a member, or that would cycle. And answering that
  go with the pair's `400`: this paragraph does not name those codes.
- Not checking at `go`, as the cross-owner edge does for the asker's rights (there the asker's rights do
  not decide what the owners agreed; here the asker's change is what is applied). Withdrawing the request
  in the same call: the answer is the owner's and cannot be undone from inside it. Counting an open
  request as a use of a project role: removing a role is then refused by a request the owner may never
  answer; the `go` refuses instead.

A target that became a reviewer, a tester or the contract arbiter while the request waited would need the
project owner's go for an admin agent's change (§2.3 ᵃ); here the agent owner's `go` is the only consent
asked, decided so: it is the owner of that very agent who agrees to exactly the values shown.

**Not covered, and decided so:**
- The withdrawal of the request by anyone but the asker on the project route (the owner withdraws and
  answers under `/requests/{id}`); the contract gives no further rule.
- A caller with `members:admin` never takes the manager's path, so a manager who also holds
  `members:admin` asks the agent's owner even for a member of its reach; only a `line:lead` caller
  without `members:admin` changes another owner's agent in its reach at once. Rejected: checking the
  reach for an admin caller too; the admin and the line paths stay apart as in §2.3.

## A change of another owner's agent is one personal consent request that applies the whole change at go

**Id:** 0530e4cd-b339-4d49-8a0a-25f175f05dd1
**Type:** decision
**Status:** superseded
**Superseded by:** e201515c-83ac-4d96-863e-b30c6c03da96
**Evidence:** inferred
**Verification:** contradicted — the sentence that sends `reports_to` its own way. A `reports_to` that stays inside the agent's owner waits on the same request, recorded by the successor.
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
function its call runs too, so the two lists cannot drift, and a lift of one instance's pause asks the
instance's own credential again, `check_instance_pause`); and the role is read again from the
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
