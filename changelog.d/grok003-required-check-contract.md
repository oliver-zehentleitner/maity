### Added

- docs/api.md §6.1, §6.6, §6.13, §8.2, §11: a project names its required check
  (`repository.required_check`, default `null`, kept by a `PATCH` that leaves it out on the
  same `url`); a report's observation carries `required_check` `{name, status}` from the pull
  request's own check read, with `cancelled` as its own state (never "superseded") and only the
  latest result of each check counting; a card links a commit (`kind: commit`), observed as
  `{found, sha, checks, required_check, branch_head_sha, ahead}`, `ahead: true` waking the
  card's holder; `GET …/probe?commit=`; branch reads stay head-only; a first or renamed
  `required_check` wakes nobody; a spent forge budget reads as `unknown` or the last complete
  observation, never as a partial one.
