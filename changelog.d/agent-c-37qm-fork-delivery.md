### Fixed

- hub: a report whose pull request comes from a fork is no longer a `mismatch` because the
  project's repository has a branch of the same name at another head; the probe does not
  compare that branch when the pull request it read names another repository as its head's
  (`head_repo`). A report whose pull request was not read, or whose read names no head
  repository (an observation from before the hub kept it, or a head repository that is
  gone), is compared as before (§6.6). Before, the admins were woken and the merge was never told to the done authority.
- cli: `maity report` from a fork's clone finds the pull request in the project's repository:
  it asks gh with `--repo`, the repository the last `maity resume` named, when that is on a
  host gh is asked about. Before, gh looked in the repository it picked from the clone's
  remotes, the fork when `origin` was the only one, and the report said "no pull request".
