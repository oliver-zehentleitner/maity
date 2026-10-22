### Changed

- ci: changelog entries are one file per pull request in `changelog.d/` instead of lines under
  `[Unreleased]` in `CHANGELOG.md`; `tools/changelog.py check` validates them (a `changelog` job
  in the `ci` workflow), `tools/changelog.py release <version>` folds them into `CHANGELOG.md`
  and deletes them. The entries that were under `[Unreleased]` moved to
  `changelog.d/unreleased-before-fragments.md`.
