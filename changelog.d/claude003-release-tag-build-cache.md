### Changed

- ci: publish-image builds the hub image for a release tag or a hand-started
  run without a build cache shared with other refs: no `cache-from`, no
  `cache-to`, and the build for the check with `no-cache` (tsk-6zh891gy6cvz,
  point 1).
