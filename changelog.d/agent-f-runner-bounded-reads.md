### Security

- cli: `maity runner` reads files on the agents' side (a clone's
  `.git/config`, logs and state) as regular files only, without following
  a link at any step below the clone or the agents' directory or
  waiting, up to a fixed size and within a time limit, and inspects an
  existing clone only in the task that starts its agent.
- cli: `maity runner` holds each placement's log to
  `limits.log_keep_bytes` (keeping the newest output), counted from the
  file's real size, so bytes another writer appends are cut too, and a status file
  that cannot be written while serving is retried with backoff instead of
  ending the service.

### Changed

- cli: an ssh host of `maity runner` needs a `maity` of the same version
  for its reads on the agents' side; with an older one, an existing clone
  on that host is refused as `origin_mismatch` until it is updated.
