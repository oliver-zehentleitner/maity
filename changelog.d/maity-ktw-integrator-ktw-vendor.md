### Added
- web: the Keep the Why views library vendored in `web/vendor/keep-the-why/` (keep-the-why-dashboard 0.11.39), by
  `web/tools/vendor_ktw.py` from the pinned PyPI wheel, with the sha256 of the wheel and of every file; `make check`
  verifies them and the forbidden calls, `web/tools/vendor_csp.py` mounts the views in Chromium under
  `default-src 'self'` in CI, and the `ktw-vendor` workflow opens a pull request for each new release.
- web: `vendor_ktw.py --verify` compares the vendored files byte for byte with the locked release, fetched again from
  PyPI; CI runs it in a `web-vendor` job whenever `web/vendor/` changes.
- hub: the dashboard's vendored libraries are served under `/assets/vendor/`, and the wheel carries `web/vendor/`.
