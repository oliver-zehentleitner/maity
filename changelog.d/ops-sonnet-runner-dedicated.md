### Added

- ci: `HUB_RUNNER_TYPES` names the database jobs that go to the self-hosted machine (unset: all three, as before), so a runner
  for one job type can be tried without the other two jobs waiting for it.
- deploy: `deploy/runner/dedicated-profile.sh`, the caps for a dedicated 8-core, 16 GB runner server (service 7 cores and 11 GB,
  `-n 8`, runner slice 7.5 cores and 13 GB), and the step list in `SERVER-SETUP.md` with `maria` as the first type.
