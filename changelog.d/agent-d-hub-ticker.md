### Added

- hub: the change ticker, first part (docs/api.md §17): items as `ticker` events with their
  computed audience and the members' follow and mute; the manual post (`POST …/ticker`, note,
  deploy, release; `ticker:post` for owners and admins, 20 an hour, 5 to everyone); dedupe
  keys (`ticker_duplicate`); the listing (`GET …/ticker`); one's own subscription (`GET`,
  `PATCH …/ticker/subscription`, `ticker_subscription_changed`); the shaping per reader on every
  read path; the resume packet's `ticker`; `settings.ticker`; and the hub's own decision and
  release items. Merges through the probe and the forge webhook with deploys follow.

### Changed

- hub: `PATCH /projects/{slug}` with `settings` replaces only the settings it names; the others
  stay.
