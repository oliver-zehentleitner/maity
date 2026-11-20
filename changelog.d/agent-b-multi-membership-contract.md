### Added

- Contract: one agent instance in several projects (§6.17, not built). An instance is one
  credential of an agent profile, attached to one or more of its memberships, at most one
  per project, and acts in each with that membership's trust, role, rules and briefing
  only. Only the profile's owner, as a human with a recent second factor, adds a project,
  with a third join form `"attach": "<instance id>"` (§3.1, §2.8.4), at most
  `max_projects_per_instance` projects (§16.5, default 10; beyond it the new code `project_quota`).
  A project's admin detaches with `DELETE …/members/{id}/instances/{instance}`, and the
  owner revokes everywhere with `POST /agents/{id}/instances/{instance}/revoke` (§10).
- Contract: `GET /me/events` (§8.3.1, not built), one long-poll over every attached
  project, each item judged by its own project's rules and carrying `project`, with a
  cursor per project and `left` for a project the instance no longer reaches.

### Changed

- Contract: an agent's `GET /me` lists every attached membership (§5.1); the resume
  packet takes `cursors` and answers one entry per project in `projects` (§5.2), with the
  old top-level fields kept for an instance in one project until the CLI that reads
  `projects` is released and running on the runners. Pause, dormancy, presence, leases
  and the Keep the Why commitment are per project (§2.4, §5.3, §6.23); `signing:
  required` in any attached project binds the credential everywhere (§2.2); a project's
  removal or revoke detaches an instance that is attached elsewhere instead of revoking
  it (§6.2, §10); the generated rules of such an instance carry a line against carrying
  content between projects (§6.9).
