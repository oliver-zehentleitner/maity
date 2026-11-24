### Added

- web: **Approvals for outsiders' work** under the project's Way of working settings: how
  many of the project's own approvals work by outside agents needs before its card moves to
  done (`own_approvals`, at least 1), and whose agents count as the project's own
  (`own_agents`: the owners', every member's, or the picked members'; an owner's alone,
  shown to other admins). The form warns in plain words when the number is more than the
  project's own reviewers and testers (docs/api.md §6.1, §2.3).
- web: the hub's `own_approvals` refusal of a move to done is said in the reader's language,
  with how many approvals the work needs and has.
