### Changed

- CLI: `maity report` checks a branch's upstream before asking git about it (a configured
  remote or a forge URL, a merge ref under `refs/heads/`) and refuses with the `git push -u`
  hint otherwise; maity's git runs with only the https, http, ssh, git and file transports;
  git and gh start from an absolute PATH entry, never the current directory; `gh pr view` is
  asked only about https URLs on github.com or `GH_HOST`.
