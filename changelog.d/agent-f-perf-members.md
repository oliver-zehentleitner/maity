### Changed

- hub: `GET /projects/{owner}/{slug}/members` reads the member humans and the agents' owners in one
  query, their pictures in one, all agents' instances in one pass with the projects the list already
  read, and the briefing and subagent-setting writers in one: 40 → 35 statements per read on
  PostgreSQL for an owner with 3 agents and 6 cards.
