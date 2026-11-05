### Added

- hub: released to PyPI as `maity-hub` from a `v*` tag, the same tag that publishes the image
  (`.github/workflows/release-hub.yml`), with trusted publishing; the first version is
  `0.1.0a1`. The sdist and wheel are built from a hashed release lock
  (`hub/requirements/release.txt`, `make release-build`) and proven before the upload
  (`make release-check`): the bundled dashboard and join page, a wheel rebuilt from the sdist,
  and an install outside the checkout that serves the dashboard. The `hub-dist` CI job runs
  both on every pull request that touches `hub/`, `web/` or the join page.
- docs: `hub/README.md` describes the release (tag, version scheme, `make release-build` and
  `make release-check`); the install guide names `pipx install maity` for the agent's CLI.

### Fixed

- hub: the sdist now carries the dashboard and the join page (under `bundled/`, through
  `hub/hatch_build.py`), so a wheel built from it, as pip does when it installs from source,
  no longer fails with "Forced include not found".
