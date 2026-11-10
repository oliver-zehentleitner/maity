### Added

- Hub: a project's `released_at` (§6.1) is set once, when the probe first finds the `v<version>`
  tag of one of its releases, whether or not the release card is done, and is never cleared.
  Setting it bumps `rules_version` with a `state_changed` event carrying `released_at`, and the
  rules text then names the date and the released rules. Migration 0097 fills existing projects
  from the release tags the probe has already found.
