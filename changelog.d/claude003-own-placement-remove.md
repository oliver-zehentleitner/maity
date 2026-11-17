### Fixed

- web: the project's **Managed agents** page offers **Remove** on every placement whose
  runner or agent is the viewer's, not only on one someone else made (`foreign`), as the hub
  allows the `DELETE` (docs/api.md §15.6). An agent of one's own can now be moved to another
  runner from there, where a start elsewhere was refused with `placement_exists`.
