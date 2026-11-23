### Fixed

- hub: creating a placement that will create an agent profile reads its handle under the
  handle's lock, so a `POST /agents` or a join with the same handle at the same time waits
  for it and is refused `taken`, instead of both succeeding and the runner's pickup refusing
  the placement later (`handle_taken`).
