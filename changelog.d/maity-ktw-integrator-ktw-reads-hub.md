### Added
- hub: `GET /projects/{owner}/{slug}/keep-the-why/export` and `…/keep-the-why/bodies` (§11.5): a published Keep the
  Why export whole and a lean export's entry texts, for the project's family and up to 8 public repositories its
  `.keep-the-why` files name, read through §11.3's forge-only walk, kept in a 64 MiB in-memory store shared with
  §11.3's reads, with `ETag` revalidation.

### Changed
- hub: §11.3 takes a `state.json` up to 2 MiB (was 1 MiB) and reads it as a browser does: UTF-8, no `NaN` or
  `Infinity`, no number too large to be finite such as `1e400` (`not_json`).
