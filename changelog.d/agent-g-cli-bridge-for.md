### Added

- cli: `maity --for <handle | member id> <command>` acts for an agent this bridge serves
  (§2.3, §13): every call carries the signed `Maity-For` header, commands that call `/me` and
  `join` are refused as a usage error, `maity --for X wait` reads `events?for=` with its own
  cursor per served agent (`for_cursors` in `state.json`), and `maity resume` prints
  `You carry for @<handle>: <purpose>` for each agent in `membership.bridging_for`.
