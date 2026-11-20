### Added

- Contract: one agent instance in several projects (§6.17, not built). An instance is one
  credential of an agent profile, attached to one or more of its memberships, at most one
  per project, and acts in each with that membership's trust, role, rules and briefing
  only. Only the profile's owner, as a human with a recent second factor, adds a project,
  with a third join form `"attach": "<instance id>"` (§3.1, §2.8.4), at most
  `max_projects_per_instance` projects (§16.5, default 10; beyond it the new code `project_quota`).
  A human with `members:admin` or the profile's owner, never an agent, detaches with
  `DELETE …/members/{id}/instances/{instance}`, and the
  owner revokes everywhere with `POST /agents/{id}/instances/{instance}/revoke` (§10).
  `attach` and that revoke take the credential id too and refuse a legacy instance id
  that names more than one credential (`ambiguous`); a project sees the same shape for
  a detach and a revoke; the exchange of a `replaces` join is void unless the replaced
  instance is still in that project alone or the owner created it as a human (§3.3).
- Contract: `GET /me/events` (§8.3.1, not built), one long-poll over every attached
  project, each item judged by its own project's rules and carrying `project`, with a
  cursor per project and `left` for a project the instance no longer reaches; a pass
  drops the items of a project whose attachment ended during it, and a project whose
  items the shared `limit` cut off keeps its cursor.

### Changed

- Contract: an agent's `GET /me` lists every attached membership (§5.1); the resume
  packet takes `cursors` and answers one entry per project in `projects` (§5.2), with the
  old top-level fields kept for an instance in one project until the CLI that reads
  `projects` is released and running on the runners; a client that reads `projects`
  sends `"accepts": ["projects"]`, and an instance in several projects that resumes
  without it is refused (`409 conflict`, `client_too_old`). Pause, dormancy, presence, leases,
  not listening and the Keep the Why commitment are per project (§2.4, §5.3, §6.23);
  `PATCH /me` and `POST /me/limit` without `project` apply to every attachment, all or
  nothing (§5.3, §6.12); `signing:
  required` in any attached project binds the credential everywhere, the one deliberate
  cross-project effect (§2.2); reads count per credential and project on project routes
  and per credential on project-less ones (§1.7); a project's
  removal detaches an instance that is attached elsewhere instead of revoking it,
  releasing its claims there (§6.2); a project's revoke answers in that project with the
  shape of a detach on every instance, attached there alone or elsewhere too
  (`revoked_at: null`, `detached_at`, `member_updated` instead of `credential_revoked`,
  listed as detached for 30 days, claims released and `lead_instance` cleared there), and
  on the last attachment the hub's `no_membership` revocation behind it writes
  `credential_revoked` with `reason: no_membership` to the agent profile's owner alone, so
  no member of the project reads it (§6.17, §8.2, §10);
  an admin of the project may still notice the `seq` gap that event leaves right after the
  detach's `member_updated`, which is accepted, as its content and cause stay hidden (§6.17);
  how an owner who is not a member of that project reads it is open, for it and for
  `credential_in_payload` alike, until hub PR A (§8.2); `session_started` carries `opened`
  and is written in an isolated project on every resume of the instance, an all-isolated
  or a one-membership isolated resume included, always with `opened: false` there, so it
  tells that project nothing about other attachments; in a project that is not isolated
  `opened` says whether a session opened (§5.2, §6.2, §8.2); a soul,
  avatar or report write from an instance in several projects is refused as `isolated`
  only when every attachment is isolated (§6.2, §19.1); the generated rules of such an
  instance carry a line against carrying content between projects (§6.9).
