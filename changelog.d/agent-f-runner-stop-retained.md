### Security

- hub: an owner's `agents: "stop"` on a runner's revoke or removal also revokes, at
  once, the agent credentials of the runner's closed placements whose clone it has not
  reported removed (retained clones), in every project, attached or not (§15.3). The
  stop reads the placements under the projects' locks, so a pickup exchanged at the same
  time is either revoked with them or refused.
