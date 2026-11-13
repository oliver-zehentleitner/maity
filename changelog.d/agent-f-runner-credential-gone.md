### Fixed

- hub: every revocation of a runner credential now ends the runner's unused pickup
  joins and closes its closing placements in the same transaction, so a re-pair and a
  suspension of the runner's owner do it too, not only a revoke and a leaked credential
  (§15.9). A re-pair leaves a closing placement closing: the new credential reports its
  end (§15.3).
- hub: suspending an account stops each of its runners as an owner's `agents: "stop"`
  does, whatever the project's `on_runner_revoke`: their placements close and the agent
  credentials they named are revoked at once (§15.3, §16.8).
