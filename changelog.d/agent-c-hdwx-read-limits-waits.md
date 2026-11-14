### Changed

- hub: the Keep the Why views' reads (`…/keep-the-why/export`, `…/bodies`, §11.5) wait
  at most 0.5 s for a read already under way or a free place among the reads in flight,
  then answer the file the hub holds with `fresh: false`, or `ktw_unavailable` with
  reason `timeout` when it holds none.
- hub: a contract's text and the whole contract (§6.8) keep the default branch's head
  for up to 30 s per forge token, repository and branch: a new commit shows within
  30 s, and a read the hub holds is answered without asking the forge.
