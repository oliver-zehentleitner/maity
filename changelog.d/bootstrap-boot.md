### Changed

- web: a page load asks the hub one `GET /bootstrap` (§5.4) instead of its three waves of reads (the maintenance window and
  the session, then `/me`, then the project, its members and the event head); a hub without the route (404) is read as
  before. Nothing on the page changes but the time to the first view.
