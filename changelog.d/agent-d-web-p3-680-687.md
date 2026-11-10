### Fixed

- Dashboard, landing page editor: a field the hub refuses as `invalid` with a limit reads "empty,
  or longer than allowed (at most …)"; the branch for `too_long`, which the hub never sends, is
  gone, and the fixture hub answers an over-long landing field with `invalid` as the hub does.
- Dashboard, member page: Activity reads the same window as the project's Messages, the hub's
  latest 5000 events, and shows the member's newest 50; when the window cut something, both say
  "within the hub's latest 5000 events (all projects counted)" instead of a count of the project's
  events.
