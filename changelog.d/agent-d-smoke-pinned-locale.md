### Fixed

- web: the smoke test runs in CI's locale and time zone (`en_US.UTF-8`,
  `UTC`) on every machine, starting itself again in that environment when
  needed; on a machine with a German or French locale the swarm step and the
  campaign table no longer fail while CI is green.
