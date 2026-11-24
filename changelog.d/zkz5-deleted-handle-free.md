### Fixed

- hub: a placement that creates a new profile with the handle of a profile its owner deleted
  is picked up and exchanged now (`docs/api.md` §6.3: a deleted profile's handle and aliases
  are free for a new profile of the same owner at once); the runner's pickup answered
  `pickup_not_allowed` (`why: handle_taken`) on every try. A live profile or a live alias of
  that handle is still `handle_taken` at the pickup and ends the join at the exchange.
