### Fixed

- hub: a human's direct chat message wakes the agent's team by its `wake` rule (docs/api.md §9.1, §6.18) instead of every instance: under `lead` only the lead instance, under `next_free` the listening instance with the fewest claims, and nobody when such a team has no listening instance (the message waits in the next resume); under `all` nothing changes. A message that names an instance (`to_instance`) still wakes that one only.
