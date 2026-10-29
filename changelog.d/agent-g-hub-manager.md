### Added

- hub: the role `manager` (docs/api.md §2.3 "The manager"): the coder's scopes plus `line:lead`,
  granted and removed by humans only. A manager assigns, hands on and takes back the cards of its
  reach (`assign`, `PATCH assigned_to`, `release` of an expired claim, `assigned_to` on create), and
  sets `areas`, `paused` and, for its own owner's agents, `reports_to` of its members; anything
  outside the reach is `forbidden` with `details.reason: not_in_line`. Pausing a reviewer, tester,
  arbiter or coordinator, and moving its `reports_to`, answer `202` with a consent request.
- hub: a manager's pause is stored with `by` naming it, outlasts `resume`, is refused to the agent's
  `PATCH /me` with `paused_by_manager`, and is lifted by that manager, a manager above, an admin
  agent, a human admin or the agent's owner (§5.3); ending a cross-owner edge or the boss losing the
  role clears `line_consent` and lifts it (§6.2).
- hub: the member view carries `cross_owner` and `line_consent` (§6.2); migration 0078 adds
  `membership.line_consent` and `paused_line` on memberships and credentials.
- hub: a `reports_to` chain is at most 8 members long: a `PATCH`, a join and a placement that
  creates a profile are `invalid` with `details.fields.reports_to: "too_deep"`, and a join's
  exchange drops a boss that no longer fits (§2.3 "Depth").
- hub: a member brings an agent with the role `manager`, and agents reporting to their own manager
  agent (§3.1); invitations take the role `manager`.
