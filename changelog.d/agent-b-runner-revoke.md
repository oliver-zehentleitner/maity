### Added

- hub: what revoking or removing a runner does to its agents (`docs/api.md` §15.3, §6.1,
  §16) — `policy.on_runner_revoke` (`keep`, `stop`, `inherit`, the default; kept on a preset
  change) within the instance setting `MAITY_ON_RUNNER_REVOKE` (`keep`, the default, `stop`,
  or `stop_floor`, under which a project's `keep` is refused with `stop_floor`); the owner's
  `agents: "stop"` on `POST /runners/{id}/revoke` and `DELETE /runners/{id}` stops in every
  attached project; `stop` closes the runner's placements there at once (`runner_revoked`,
  under `DELETE` `runner_removed`), tells each agent, and revokes their credentials
  `stop_grace_seconds` later (at once under the override); the answer carries
  `on_runner_revoke: [{project, rule, stopped}]`, `runner_credential_revoked` the rule and
  the stopped placements, and the revoked runner's next call `details.stop` (migration
  `0019_on_runner_revoke`)
