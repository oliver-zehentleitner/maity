### Fixed

- web: the project's **Managed agents** page offers **Remove** on an active placement whose
  runner is the viewer's or whose agent the member list names as the viewer's, not only on one
  someone else made (`foreign`), as the hub allows the `DELETE` (docs/api.md §15.6). A placement
  waiting for consent, to start or for a change, still offers no action there; its request in the
  inbox answers it. An agent of one's own can now be moved to another runner from there, where a
  start elsewhere was refused with `placement_exists`.
