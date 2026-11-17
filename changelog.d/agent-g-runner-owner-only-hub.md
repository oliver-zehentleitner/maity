### Changed

- hub: only a runner's owner places agents on it, wherever the runner is attached
  (docs/api.md §15.4, §15.6). Creating a placement, changing its spec, starting and
  restarting it are for the runner's owner and the agents whose profile that owner owns;
  anyone else gets `forbidden` with `details.reason: "runner_owner_only"`. An agent's
  proposal goes to the runner's owner as a personal request, answered under
  `/requests/{id}/answer`; `policy.spawn_consent_by` no longer decides who answers it.
  A consent request filed as a project request before this release is answered only by
  the runner's owner too.
- hub: the runner's owner stops and deletes every placement on their runner, also in a
  project they are not a member of; there the answer is the runner owner's line only,
  and a repeat with the same `Idempotency-Key` replays that line.
- hub: the agent profile's owner deletes their agent's placement too, so a placement on
  someone else's runner ends and the agent is placed again on a runner of their own.

### Added

- hub: `GET /runners/{id}/placements`, the owner's list of the active placements on their
  runner across projects, and `foreign` in the placement view (§15.3, §15.5).
