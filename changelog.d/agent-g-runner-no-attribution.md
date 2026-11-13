### Fixed

- cli: the runner's Claude Code settings set `attribution` to empty `commit` and `pr` texts and
  `sessionUrl: false` for every placement, so agents no longer add a `Co-Authored-By` trailer to
  commits or a "Generated with Claude Code" line to pull request bodies. Takes effect on a
  placement's next start.
