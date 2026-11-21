### Changed

- ci: `hub-sqlite` runs the hub's suite in three shards by test file, side by side, like
  `hub-postgresql` (`hub-sqlite (1)` to `(3)`), each with its 90-minute limit; lint and types run
  in the first shard. The whole suite in one job had reached 82 of the 90 minutes.
