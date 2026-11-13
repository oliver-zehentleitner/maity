### Added

- contract: the runner installs and updates the harness tools and maity itself, opt-in per tool
  in its configuration (`install`, `update = "daily"`), never under a running session, with the
  previous version kept; it reports each tool's version and state in `capabilities.tools`, and the
  runner's owner asks for an update with `POST /runners/{id}/updates`, which the runner reads with
  `GET /runner` (docs/api.md §15.16, tsk-29nmydbzrg5z). Not built yet.
