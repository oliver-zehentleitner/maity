### Added

- tools/pr.sh: open a pull request (`open`) or edit its title and body (`edit`) over GitHub's REST
  API, for sessions where `gh pr create`/`gh pr edit` cannot reach GraphQL. Origin's repository and
  host only; `open` needs the branch pushed at the local head; `edit` only the checked-out branch's
  pull request; the body from a file, sent as it is, and refused with an attribution line.
  CONTRIBUTING.md says how; opening pull requests for cloud sessions is no longer the lead's job.
