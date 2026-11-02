### Added

- docs/api.md §6.1, §6.6, §6.13, §8.2, §11: a project names its required check
  (`repository.required_check`, default `null`); a report's observation carries
  `required_check` `{name, status}` with `cancelled` as its own state; a card links a commit
  (`kind: commit`), observed as `{found, sha, checks, required_check, branch_head_sha, ahead}`,
  `ahead: true` waking the card's holder; `GET …/probe?commit=`; a spent forge budget reads
  as `unknown` or the last complete observation, never as a partial one.
