### Added

- Contract §15.13: `maity runner <harness> --join <url>`, local mode. One
  agent in the foreground on the person's own machine, on Linux and
  Windows, with no pairing and no placement: the credential in the
  workspace's `.git/maity` (mode 600, or an access list for the user
  alone on Windows), the next run only when work waits, with backoff,
  stopping by signal, Ctrl-C or console close, and how it stays apart
  from the full runner.
