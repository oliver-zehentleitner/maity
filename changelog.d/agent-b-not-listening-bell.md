### Added

- hub: under `not_listening.mode: bell` an owner hears of their agent instances that are
  away (an episode longer than the project's or the personal threshold) as the bell item
  `agents_not_listening` (kind `inbox`, `target: {type: "agents"}`, linking to `/agents`,
  `<n> of your agent instances are not listening`), listed and counted while one is
  away; the hourly worker runs on the hour (UTC) and a change of the mode takes effect
  at the `PATCH` (§5.3, §18.1, §18.2)

### Changed

- hub: the request per not-listening episode goes only to an owner under
  `not_listening.mode: inbox`; under `bell` the bell item replaces it, under `off`
  nothing is sent, and the first hour after the mode left `inbox` withdraws the requests
  of episodes still running (§5.3, §18.4)
