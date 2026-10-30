### Changed

- hub: `make revision` names a new migration by its UTC time and slug (`20261030102512_add_the_tasks`)
  instead of the next number, so parallel pull requests never take the same id; the numbered migrations stay.

### Added

- `tools/rechain.py` (`make rechain` in `hub/`): after merging `origin/main`, sets the branch's one new
  migration's `down_revision` to main's head; refuses two new migrations or a branch that lacks main's.
- CI: the changelog job fails when the hub migrations have two heads and names `tools/rechain.py`.
