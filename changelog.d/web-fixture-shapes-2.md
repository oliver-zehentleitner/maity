### Changed

- web: the fixture shape check covers 9 more requests (notifications, requests, agents,
  credentials, the board's full list, notes, history), and the hub seed fills the lists it
  compares.

### Fixed

- web: a notification of a project the reader is no member of now leads to `/all`; the
  dashboard read membership from the item, where the hub does not send it, instead of from
  `by_project`.
