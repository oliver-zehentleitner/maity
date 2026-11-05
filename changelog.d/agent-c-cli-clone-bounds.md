### Changed

- CLI: `maity report` checks a branch's upstream before asking git about it (no value that
  reads as an option or names a remote helper, a merge ref under `refs/heads/`) and refuses
  with the `git push -u` hint otherwise; the git maity runs through `proc.run` uses only the
  https, http, ssh, git and file transports (narrowed further by an operator's own
  `GIT_ALLOW_PROTOCOL`), and a program `proc.run` starts by name comes from an absolute PATH
  entry, never the current directory; `gh pr view` is asked only about https URLs on
  github.com or `GH_HOST`.
