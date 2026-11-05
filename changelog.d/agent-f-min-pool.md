### Changed

- hub: with several workers, each process needs one connection of the pool, not two. A measurement on PostgreSQL found no request handler in the measured tests that held two serving connections at once. A share of 0 is still refused, since SQLAlchemy reads it as no limit.
