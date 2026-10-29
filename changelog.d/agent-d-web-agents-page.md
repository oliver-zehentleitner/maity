### Added

- web: **Your agents** (`/agents`, `/agents/<id>`) in the gear menu: every agent profile of the human
  across projects, with its picture, its memberships (trust, role, instances against the team's
  limit), its name, git identity and handle, its deletion, and a new profile (`POST /agents`,
  `PATCH /agents/{id}`). **Add to a project** opens that project's join panel with the profile
  chosen (`…/members/join?agent=<id>`), kept across a Try again. The handle is offered where the
  hub's machine form names it on `PATCH /agents/{id}`. The fixture hub answers `POST` and
  `PATCH /agents`.

### Removed

- web: the account's **Agents in other projects** and `/account/picture/<agent id>`; an agent's
  picture, name and deletion are on Your agents.

### Fixed

- web: an open join panel redraws its instance count when the rulebook is saved, the chosen agent
  kept; every view that reads the members again sets the list and its index by id together.
