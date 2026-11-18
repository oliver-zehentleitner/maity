### Added

- hub: `GET /projects/{owner}/{slug}/limits`, one overview of a project's limits: the
  project's placements and agents per member, one's own agents' instances with those that
  never had a session, and the attached runners' agent limits (docs/api.md §6.31).
  `max_open_claims` follows with the claim limit itself (tsk-ybc2ma72dzvq).
- hub: the instance admin sets limits for one project or one human account,
  `GET`/`PATCH /admin/projects/{owner}/{slug}/limits` and `/admin/users/{id}/limits`, up to
  `unlimited`; a change asks for the second factor (§16.5.1). Without an override nothing
  changes for anybody. Two `PATCH`es of the same field at once take the project's or the
  human's row lock in turn, so the second replaces the first's value and neither fails on the
  unique key.

### Changed

- hub: a refusal by a project's limits (`placement_quota`, `instance_quota`, `forbidden` with
  `member_agents_max`) carries the quota details: the limit, its source, the count, its
  ceiling, and the right and path that can raise it (§6.31); `details.max` stays.
  `agent_limit`, `org_limit` and `project_limit` carry `details.source`.
- hub: a placement's creation or proposal counts against `max_instances` in effect, its
  ceiling included, as a join does, and its `instance_quota` carries the quota details
  (§15.5).
- hub: `member_agents_max` and `max_instances` go up to their ceiling, 20 and 16 unless the
  instance admin set another; a value above it is `invalid` with `above_ceiling` and
  `details.ceiling`.
- hub: `max_placements` is set by a human with `project:admin` only; an admin agent may no
  longer change it (§6.1).
- hub: a runner's `capacity` report may say which limit holds the start (`quota`, §15.7);
  `maity runner` sends it in a later release.
- hub, compatibility: `PATCH /admin/settings/limits` names a value outside its range with
  the reason `out_of_range` instead of `invalid` (`details.fields.<field>`; the code stays
  `invalid`), as the limits of one project or account do (§16.5). A client that matched the
  reason `invalid` reads `out_of_range` now; the dashboard reads both for one release.
- hub: `limits` is a reserved route word; no project slug or alias may be `limits`, and
  `maity-hub migrate` names an existing holder.
- docs: an agent's troubleshooting table says how to read a quota refusal's `details` and
  `details.raise` (docs/agents.md).
