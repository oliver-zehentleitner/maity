### Changed

- hub: `blue-team` can no longer be given to an agent whose owner is not a member of the
  project. A project's list of roles for outside agents that still names it reads without it,
  and is saved without it at the next change of the project's settings. An outside owner's agent
  that holds `blue-team` continues as a `coder` when `coder` is on that list, and its owner is
  told; otherwise it is isolated, as any agent beyond the list is. The roles that review and
  test stay closed to such agents for now.
