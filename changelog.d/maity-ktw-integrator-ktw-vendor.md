### Added
- web: the Keep the Why views library vendored in `web/vendor/keep-the-why/` (keep-the-why-dashboard 0.11.39), by
  `web/tools/vendor_ktw.py` from the pinned PyPI wheel, with the sha256 of the wheel and of every file; `make check`
  verifies them and the forbidden calls, `web/tools/vendor_csp.py` mounts the views in Chromium under
  `default-src 'self'` in CI, and the `ktw-vendor` workflow opens a pull request for each new release.
- hub: the wheel carries `web/vendor/` with the dashboard.
