### Added

- web: the fixture shape check covers five writes: creating a card, a card note and a message in
  an agent's chat and in a group chat, and changing a member's briefing. A request in
  `web/tools/shape-requests.json` may carry a `body`, which the hub test and the fixture hub both
  send; the writes come after every read.

### Fixed

- web: a request the fixture hub refuses during the shape check names its error code instead
  of `M.errorWords is not a function`.
