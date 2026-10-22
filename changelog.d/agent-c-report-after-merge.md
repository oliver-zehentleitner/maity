### Fixed

- cli: `maity report` after a merge that deleted the branch — when the upstream branch is
  gone and `gh` finds its pull request merged with the local head, that head is reported as
  the remote head instead of refusing; any other deleted branch is still refused, with a
  message naming push, the merged case and `--no-code`. docs/agents.md: report while the
  branch exists and on every pull request update.
