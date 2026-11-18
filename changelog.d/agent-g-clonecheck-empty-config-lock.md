### Fixed

- cli: maity no longer refuses a placement's clone over the empty
  `.git/config.lock` the Claude Code sandbox leaves to keep `.git/config`
  unwritable, so `maity report` and `checkpoint` run there again; a
  non-empty `config.lock` is still refused.
