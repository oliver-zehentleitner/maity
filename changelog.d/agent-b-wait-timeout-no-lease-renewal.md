### Added

- hub: `GET …/conversations` takes `renew=false` (default `true`): the read renews no lease
  of the caller's, or with `Maity-For` of the bridge's for the served agent, and still writes
  presence; any other value than `true` or `false` is `invalid` (§9.3, §2.4, §6.5).

### Fixed

- cli: the unread-chats read `maity wait` makes on a timeout sends `renew=false`, so an agent
  that only waits no longer renews its claims once per timeout (§13, §2.4). Against a hub
  without the parameter it renews as before.
