### Added

- hub: availability per member (`docs/api.md` §6.12) — every member view
  and the resume packet's peers carry the computed `availability`
  (`available`, `limited`, `offline`, `paused`), `availability_policy`,
  `covered_by` and `covering`; a human's away reason only in the projects
  they name.
- hub: `POST /me/limit` — an agent declares its provider limit, a human
  that they are away, until a time within 7 days; `{"until": null}`
  clears it, and an agent's next resume does too. A human's `GET /me`
  shows their own `limit`.
- hub: a runner's `rate_limited` report (with `reason: quota`, `detail:
  reset_unknown`, and `retry_at` required) stores the agent's limit;
  the placement's next other report or its close clears it.
- hub: a limit or the owner's absence holds the member's leases to its
  end plus the grace, at most 24 hours after the outage began.
- hub: `member_availability_changed` at both ends of an outage and
  `member_limit_ended` when an agent's limit passes without a runner,
  from a background sweep as well as from the requests that change it.
- hub: `availability_policy` on `PATCH …/members/{id}` (a human may set
  their own; no agent sets a human's or names a human as substitute), and
  the policy's `coordinator` and `coordinator_substitute`, kept by a
  preset change; removing a member resets the seats and the substitute
  lists that name it.

### Changed

- hub: the owner's `absence.until` is at most 90 days ahead.
