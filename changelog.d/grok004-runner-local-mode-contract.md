### Added

- Contract §15.13: `maity runner <harness> --join <url>`, local mode. One
  agent in the foreground on the person's own machine, on Linux, macOS
  and Windows, with no pairing and no placement: the credential in the
  workspace's `.git/maity` (mode 600, or on Windows an access list for
  the user, `SYSTEM` and `Administrators`), a runner's adapter context
  with the sandbox `maity runner check` reports, the one Git fetch on the
  runner's transport list, only in a staging directory local mode just
  created, a harness only in a workspace marked `checked-out` after a
  complete checkout, a retry in a fresh one for any workspace without
  the mark that moves the old one aside instead of deleting it and
  marks the fresh one, and the old one before it is moved aside, with the
  one path it may run at, so at any one time only the copy at that path
  starts and a start in any other is refused every time (the mark
  compared by the directory's identity, not its spelling, printed when
  written and when rewritten, and removed once the copy is at its path;
  by hand only when that path holds another instance or nothing, after
  the person checked that no other copy exists; not covered: a leftover
  the person did not remove, renamed onto the path after the copy there
  moved on, and a `.replaced-*` the person makes by hand, which carries
  no mark), one
  lock per workspace path outside every renamed directory, keyed by the names
  the file system stores, held by local mode alone across the renames
  and the harness's start, so at most one harness runs per path while
  local mode lives (a run that outlives a crashed local mode is not
  covered yet: tsk-3tzhegcrr48h; until then the person checks for one
  before restarting), with a table of a
  workspace path's states, its crash states each with how it is found,
  no link or hard link followed into `.git/maity` at any use, the IPv6
  host directory always with its port, the next run only when work
  waits, with backoff, stopping by signal, Ctrl-C or console close, and
  how it stays apart from the full runner.

### Changed

- Contract §5.3: the not-listening rule leaves out a supervised session
  only while an active placement names its credential, so a stopped
  local mode shows as not listening. Not built yet: the hub follows in
  tsk-mcd2xwwa2fzv; until then a stopped local mode stays silent and its
  lead sees only `away` and `offline`.
