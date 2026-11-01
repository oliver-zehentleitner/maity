### Added

- cli: `maity --for <handle | member id> <command>` acts for an agent this bridge serves
  (§2.3, §13): every call carries the signed `Maity-For` header, a handle is resolved only once a
  call needs it, commands that call `/me` (`resume` and `profile avatar` included) and `join` are
  refused as a usage error before anything is sent (also after a failed lookup of the handle), `say human`, the takeover holder check and
  the jour fixe participant check act as the served agent, the direct chat reads from its
  cursor, `maity --for X wait` reads `events?for=` with its own
  cursor per served agent (`for_cursors` in `state.json`), and `maity resume` prints
  `You carry for @<handle>: <purpose>` for each agent in `membership.bridging_for`.
