### Changed

- web: the "On a runner" part of Join an agent starts another instance of
  an agent that already runs, on the same runner or another one, while
  the agent has room under its `max_instances`: it says how many of its
  instances run and where, and which clone the new one gets. At the limit
  it says that the agent's owner raises the limit first, and an
  `instance_quota` refusal from the hub says the same. Before, the form
  refused every agent that had a placement.
