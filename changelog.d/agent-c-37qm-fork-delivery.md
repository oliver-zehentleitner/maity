### Fixed

- hub: a report whose pull request comes from a fork is no longer a `mismatch` because the
  project's repository has a branch of the same name at another head; the probe compares that
  branch only when the pull request's head is in the project's own repository (§6.6). Before,
  the admins were woken and the merge was never told to the done authority.
