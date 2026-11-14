### Fixed

- hub: `merged_closes: auto` no longer closes a release card when its reported pull request is observed merged. That move skipped the readiness gate (`release_not_ready`, §6.7) and the release's close (frozen data, `release_ready`). A release card now stays in `review`; `task_merged` says `closed: false` with `blocked_by` containing `release` and wakes the done authority, and the releaser closes the card after the checklist (§6.6).
