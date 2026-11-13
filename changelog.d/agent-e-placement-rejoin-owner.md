### Security

- hub: after a revocation by a person, a leak or a suspension, only the
  agent's owner restarts its placement with `rejoin: true`; anyone else
  gets `forbidden` (`owner_only`). A removed clone's revocation and a
  runner's revocation by its owner can still be rejoined by anyone with
  the restart's right (tsk-8hq77ns50kyf).
- hub: a runner's `capabilities` show a viewer who is not its owner only
  their own projects of it and the repository patterns that match them,
  and no OS `user` in a target's `isolation`; a request's placement
  summary shows no `user` either (tsk-8hq77ns50kyf).
