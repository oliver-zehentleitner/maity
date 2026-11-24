### Fixed

- hub: when the coordinator is out and covered by a substitute, and that substitute leaves
  the project or is removed, agents' new assignments are held at once (`coordinator_unavailable`,
  docs/api.md §6.12). Before, a substitute who had left could still count as available for up
  to two hours.
