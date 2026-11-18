### Changed

- cli: version 0.1.0a15 for PyPI. The runner offers the OpenCode (Grok)
  harness (#1928), and Codex starts more reliably — it drops the grant
  parts it cannot enforce (#1929) and no longer stops on its folder-trust
  prompt or on nested hidden paths (#1933). `maity wait` reconnects
  silently for up to a minute, names an outage in UTC, and takes
  `--related` (#1941). `maity roles` lists the project's built-in and own
  roles with what each means (#1920). Under a placement, a review's cites
  are checked in the runner's clone (#1914) and a review whose clone
  maity's git refuses is not sent (#1918); a placement is given a scratch
  directory beside its clone, removed when the placement ends (#1915). The
  sandbox-checked Claude Code version is raised to 2.1.325, which drops a
  version warning (#1893), and antigravity is named as offered in the
  harness lists (#1891).
- cli: **Upgrade note:** from 0.1.0a15, a Codex placement whose repository
  grant carries `allow` or `pull_requests` parts that Codex's sandbox
  cannot enforce now starts without those parts, where 0.1.0a14 refused the
  start (#1929). A runner config that was refused for this reason starts
  after the upgrade, with the unenforceable grant parts left off.
