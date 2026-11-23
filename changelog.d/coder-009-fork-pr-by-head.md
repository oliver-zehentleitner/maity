### Fixed

- cli: `maity report` from a fork's clone finds its own pull request when another fork has one
  from a branch of the same name: of the pull requests gh lists by that head branch name (at
  most 30), it takes the one whose head is the local HEAD. Before, gh's first answer could be
  the other fork's, and the report was refused over its head.
