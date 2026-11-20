### Changed

- cli: in a placed Claude Code session, the hook no longer allows an
  assignment to `MAITY_WAIT_TIMEOUT` before `maity`: such a line is
  refused outright, and the refusal names `maity wait --timeout N` as
  the way to set a wait's timeout there. Only `NO_COLOR`, `LANG`,
  `LC_*` and `TZ` may stand before `maity`. `MAITY_WAIT_TIMEOUT` keeps
  working outside a placed Claude Code session (tsk-f5fy2zq26xcy).
