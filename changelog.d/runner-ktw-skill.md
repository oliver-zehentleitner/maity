### Added

- cli: `maity runner` delivers the Keep the Why skill to the placements of a project that uses
  it: the commit the hub names, fetched with the runner's own git (https only, plain files,
  checked against a SHA-256 manifest at every start) into
  `~/.local/share/maity-runner/skills/`, and given to a Claude Code session as a plugin for that
  session only (`--plugin-dir`), readable through `Read` and never writable from the session.
  Every session gets `MAITY_KTW_SKILL_DIR`, which `maity resume` names. A skill that cannot be
  fetched starts the session without it, logged and reported as `keep_the_why_unavailable`. The
  runner's process needs to reach the skill's host (github.com by default). For now in the
  `single` layout on the runner's own host only (tsk-172s8y208whg).
- hub: the runner's placement carries `keep_the_why: {source, commit}` (`null` for a project
  without Keep the Why), and §15.7 takes the detail `keep_the_why_unavailable` with `running`.
- hub: setting `MAITY_KTW_SKILL_COMMIT`, the git commit of `MAITY_KTW_SKILL_SOURCE` a runner
  fetches; 40 hex digits, defaulting to the commit of the default source's release tag.
  `tools/ktw_pin.py` holds its comment to the release.

### Changed

- hub: upgrade note for operators who set `MAITY_KTW_SKILL_SOURCE`: set `MAITY_KTW_SKILL_COMMIT`
  to that tree's commit as well (`git ls-remote <repository> refs/tags/<tag>^{}`). A hub with
  the source set and the commit unset refuses to start.
