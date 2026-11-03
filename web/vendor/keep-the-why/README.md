# Keep the Why views library (vendored)

The Keep the Why dashboard's views (timeline, graph, family, search,
thoughts, pages) as classic scripts on `globalThis.KeepTheWhy`, plus their
stylesheet. Maity's Why view mounts them (web/context/stack.md).

- **Origin:** the `keep-the-why-dashboard` wheel on PyPI, directory
  `ktw_dashboard/web/`, at the version `VENDOR.json` names. Source:
  https://github.com/oliver-zehentleitner/keep-the-why (`dashboard/`). How a
  host mounts the files: `docs/dashboard-views.md` there.
- **Licence:** MIT, see `LICENSE` (taken from the release's tag).
- **Do not edit these files.** `tools/vendor_ktw.py --version X` writes
  them; `tools/check.py` fails when a file differs from the sha256 that
  `VENDOR.json` records, when a file is here that the manifest does not
  list, or when a script uses a call the dashboard forbids. A fix goes to
  Keep the Why, and comes back with its next release.
- **Updates:** the `ktw-vendor` workflow checks PyPI daily and opens a pull
  request for a new release, with the version, the hashes and the
  changelog link.
