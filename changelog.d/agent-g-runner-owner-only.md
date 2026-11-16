### Changed

- contract: only a runner's owner places agents on it, wherever the runner is attached
  (docs/api.md §15.4, §15.6). Only the runner's side, its owner and the agents whose
  profile that owner owns, creates a placement on it, changes its spec, moves one onto
  it, and starts, restarts or nudges one there; anyone else is `forbidden` with
  `details.reason: "runner_owner_only"`. An agent's proposal goes to the runner's owner
  as a personal request, and only that human gives the go; `policy.spawn_consent_by`
  stays and decides nothing for placements. Stopping and removing stay open as before,
  and the runner's owner may stop and remove every placement on their runner, member
  of its project or not. Not built yet: the hub and the dashboard follow
  (tsk-qgmz0yrc3g5x).

### Added

- contract: `GET /runners/{id}/placements`, the owner's list of the active placements on
  their runner across projects, and `foreign` in the placement view, true where the
  agent profile's owner is not the runner's owner (§15.3, §15.5). Not built yet.
