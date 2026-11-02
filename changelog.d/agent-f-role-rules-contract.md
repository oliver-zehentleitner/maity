### Added

- docs/api.md §6.1: `settings.role_rules`, set by a human with `project:admin`: per role (`coder`, `reviewer`,
  `tester`) a `subagent_per_card` switch, and for reviewers and testers a `checklist`; an unknown role or
  an empty item is `invalid`; a change bumps `rules_version`.
- docs/api.md §6.9: the subagent line and the checklist lines in the rules text for the caller's role.
