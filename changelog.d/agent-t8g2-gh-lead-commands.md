### Added

- cli: `maity gh` lead commands for a lead that runs as a runner
  placement: `pr merge` (squash only, by number, with a required
  `--match-head-commit` full sha; `Co-Authored-By` and generated-with
  footer lines left out of the body), `pr edit` (title and body),
  `pr ready`, `run list --commit <sha>` and `run view <run id>` (jobs by
  name, or the last 400 lines of the failed log). They need the runner
  grant `lead = true` beside `pull_requests = true` and the member's role
  `manager`, which maity reads from the hub at each call. Upgrade: to let
  a placed lead use them, add `lead = true` to the repository's grant and
  restart its placement; `maity runner check` warns about `lead` without
  `pull_requests`.
