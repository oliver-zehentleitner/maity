### Changed

- cli/README.md: in an agent session a submodule moved to another commit is hidden from
  `git status` and `git diff --cached` but still staged by `git add -A`, and `maity report`
  does not count it as uncommitted.
