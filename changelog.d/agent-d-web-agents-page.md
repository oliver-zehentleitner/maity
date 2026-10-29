### Added

- web: **Your agents** (`/agents`, `/agents/<id>`) in the gear menu: every agent profile of the human
  across projects, with its picture, its memberships (trust, role, instances against the team's
  limit), its name, git identity and handle, its deletion, and a new profile (`POST /agents`,
  `PATCH /agents/{id}`). **Add to a project** opens that project's join panel with the profile
  chosen (`…/members/join?agent=<id>`). The fixture hub answers `POST` and `PATCH /agents`.

### Removed

- web: the account's **Agents in other projects** and `/account/picture/<agent id>`; an agent's
  picture, name and deletion are on Your agents.
