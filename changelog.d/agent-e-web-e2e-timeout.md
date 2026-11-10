### Changed

- ci: `web-e2e` may run 30 minutes instead of 15, as most of the jobs `ci-ok` waits for do; its green runs had reached 893 s of the 900, and one
  was cancelled at the limit after its tests had passed.
