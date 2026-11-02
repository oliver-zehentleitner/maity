### Added

- `maity-hub loadtest purge [--apply]`: deletes every row of the load test's `lt-<n>` accounts in
  every table, their keys included; without `--apply` it only counts per table. Refused when an
  account shares a project or a row with anyone else, and on a hub not named as for the seed.
