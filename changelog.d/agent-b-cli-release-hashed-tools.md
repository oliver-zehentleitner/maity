### Changed

- CLI release (`release-cli.yml`): sdist and wheel are built from `cli/requirements/release.txt`, the
  build tools pinned with hashes, in a fresh environment and without build isolation; the checks run
  in a job of their own. `[build-system]` pins the same `setuptools`. `make lock` and
  `make lock-check` in `cli/` keep the lock current; CI checks it and builds with it, and the audit
  workflow checks it against known advisories.
