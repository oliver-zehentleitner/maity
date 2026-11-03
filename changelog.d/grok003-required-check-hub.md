### Added

- hub: a project names its required check (`repository.required_check`, null or 1–200
  characters; a `PATCH` that leaves it out on the same `url` keeps it, another `url` clears
  it); a report's observation and `GET …/probe?pr=` carry `required_check` `{name, status}`
  from the pull request's existing check read, `cancelled` kept apart from `failure`.
- hub: commit links (`kind: commit`, a full 40-hex sha, stored in lower case), observed on
  cards that are not closed as `{found, sha, checks, required_check, branch_head_sha, ahead}`
  through one cached read per sha and one cached default-branch read per project;
  `link_observed` wakes the card's holder when `ahead` turns `true`; a spent forge budget
  keeps the last observation, a refused branch reads as `ahead: null`.
- hub: `GET …/probe?commit=<40 hex>`; the answer has a `commit` key (`null` when not asked).
- web: the board and the card panel show the required check, a commit link's checks and
  whether the default branch moved past it.

### Changed

- docs/api.md §6.6, §8.2: a `required_check` cleared to `null` wakes nobody, like a first or
  renamed one; only a new status under the name of the last stored observation wakes (a
  rename back included is a new baseline).
- docs/api.md §6.13: a commit read is stored whole or not at all; an `ahead` back from
  `null` to `true` does not wake again; a card closed during a read gets no commit
  observation, and the read after closing wakes nobody.
