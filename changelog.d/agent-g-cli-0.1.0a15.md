### Changed

- cli: version 0.1.0a15 for PyPI. The runner offers the OpenCode (Grok)
  harness (#1928), and Codex starts more reliably — it drops the grant
  parts it cannot enforce (#1929) and no longer stops on its folder-trust
  prompt or on nested hidden paths (#1933). `maity wait` reconnects
  silently for up to a minute, names an outage in UTC, and takes
  `--related` (#1941). `maity roles` lists the project's built-in and own
  roles with what each means (#1920). Under a placement, a review's cites
  are checked in the runner's clone (#1914) and a review whose clone
  maity's git refuses is not sent (#1918). A negative count from the hub
  now reads cleanly: another instance's claims count is left out, a ticker
  count reads 0, and a hand-over message number of 0 or less names no
  message (#1853). The sandbox-checked Claude Code version is raised to
  2.1.325, which drops a version warning (#1893), and antigravity is named
  as offered in the harness lists (#1891).
- cli: **Upgrade note:** from 0.1.0a15, a Codex placement whose repository
  grant carries an `allow` list or `pull_requests` starts, without those
  two parts, where 0.1.0a14 refused it — but only with its sandbox on.
  With the sandbox off, such a grant still refuses the Codex start (#1929).
  A runner config refused for this reason starts after the upgrade when the
  sandbox is on, with the unenforceable grant parts left off.
