### Fixed

- cli: disable automatic OpenCode snapshots in runner placements. Initializing a snapshot's Git store can set `core.worktree` in the placement clone and cause the runner to refuse its next start.
