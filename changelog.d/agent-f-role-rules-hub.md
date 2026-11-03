### Added

- hub: `settings.role_rules` (§6.1): per role (`coder`, `reviewer`, `tester`), a project turns on
  `subagent_per_card` and gives reviewers and testers a checklist of up to 30 items. Only a human
  with `project:admin` sets it; an agent is refused with `humans_only`. A change emits
  `project_updated` (each checklist announced as `true`) and bumps `rules_version` once with
  `rules_changed` (`reason: "settings.role_rules"` when the `PATCH` gives none). The generated
  rules carry the lines as the section `## Set by the project for your role`, after the naming
  line, for the caller's role; a security team and a project role read as their base (§6.9). The
  generated text's digest changes, so every project's `rules_version` bumps once at the deploy.

### Changed

- docs/api.md §6.1: the role rules' refusals name the field with its full path,
  `settings.role_rules.<key>` and `settings.role_rules.<role>.checklist`, like every other
  settings error.
