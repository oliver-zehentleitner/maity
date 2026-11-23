### Fixed

- hub: a report whose pull request comes from a fork is no longer a `mismatch` because the
  project's repository has a branch of the same name at another head; the probe compares that
  branch only when the pull request's head is in the project's own repository (§6.6). Before,
  the admins were woken and the merge was never told to the done authority.
- cli: `maity report` from a fork's clone finds the pull request in the project's repository:
  it asks gh with `--repo`, the repository the last `maity resume` named, when that is on a
  host gh is asked about. Before, gh looked in the repository it picked from the clone's
  remotes, the fork when `origin` was the only one, and the report said "no pull request".
