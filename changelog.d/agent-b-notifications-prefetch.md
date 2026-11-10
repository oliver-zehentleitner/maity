### Fixed

- hub: deriving a human's notification items no longer reads the database once per event.
  The cards, requests, watches, memberships, profiles and names a project's events refer to
  are read once per answer, so an answer over thirty days of a busy project takes a fixed
  handful of queries instead of thousands. The items are unchanged.
