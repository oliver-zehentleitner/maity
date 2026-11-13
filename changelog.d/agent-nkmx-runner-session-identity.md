### Added

- cli: `[git]` in the runner configuration (`name`, `email`) is the
  author and committer of every placed session's commits, passed as
  `GIT_AUTHOR_*` and `GIT_COMMITTER_*`; without it agents commit as
  `Maity agent <maity-agent@invalid>`, and `maity runner check` warns.
  Upgrade: set `[git]` to your agents' identity, then restart the
  placements that were already running.
- docs: the runner page shows the `allow` entries for a Python
  repository's checks (`python3 -m pytest *`, `ktw-lint *`, `black *`,
  `ruff *`, `mypy *`), why each ends with ` *` for Claude Code, and that
  such a grant refuses Codex.

### Changed

- cli: placed sessions are no longer granted `git config user.name` or
  `git config user.email`.
- docs/api.md: §15.1 and §15.3 say that a repository's grant and the
  agents' git identity are the runner's configuration, which the hub
  neither sees nor checks.

### Fixed

- cli: a placed session can commit when the agents' user has no git
  identity; before, `git commit` failed with "empty ident name".
- cli: in the `single` layout placed sessions no longer commit under the
  identity in the operator's own `~/.gitconfig`.
