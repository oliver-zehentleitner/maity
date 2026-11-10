### Changed

- docs/api.md §6.2: `GET /projects/{owner}/{slug}/members` reads the humans named in the agents'
  `team.updated_by` (§6.18) together with the other people of the list. Before, it sent one more
  statement per agent whose team rulebook a human had changed, so the count grew with the project.
