### Fixed

- web: in fixture mode `DELETE /runners/{id}` answers `on_runner_revoke` as the hub does, and
  the fixture shape check now compares a runner's `capabilities` and `projects` and the
  DELETE's `still_running` and `on_runner_revoke` with their items: the hub test seeds a runner
  that has said hello, is attached and runs an agent.
