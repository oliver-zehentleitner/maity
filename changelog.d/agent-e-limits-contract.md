### Changed

- contract: a refusal by a project's limits (`placement_quota`, `instance_quota`,
  `claim_limit`, `member_agents_max`) carries one set of `details`: the limit's name, the
  value in effect and where it comes from, the count, its ceiling, and the right and path
  that can raise it, never a person; `details.max` stays. A runner's `capacity` report
  says which limit holds the start and its numbers. Not built yet (docs/api.md §6.31).
- contract: `GET /projects/{owner}/{slug}/limits`, one overview of the project's limits,
  one's own agents' instances with those that never listened, and the attached runners'
  agent limits. Not built yet (§6.31).
- contract: the instance admin may set a different ceiling, up to `unlimited`, for one
  project or one human account, and override the account values of §16.5 for one human;
  defaults stay. `unlimited` lifts the product bounds, never the hub's own bound of 1000.
  Not built yet (§16.5.1).
- contract: `max_placements` is set by a human with `project:admin`, within 0–1000.
