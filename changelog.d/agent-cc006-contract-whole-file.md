### Added

- docs/api.md §6.8: `GET /projects/{owner}/{slug}/contract` — the project's contract file read
  whole through the probe, with a table of contents and an anchor per heading, under an `ETag`;
  `settings.contract_path` (§6.1, default `docs/api.md`) names the file; a dashboard view
  `/<owner>/<slug>/contract` (§16.11) and the overview's contract row link it (§6.11).
  The setting names a Markdown file only (`.md`, `.markdown`, in any case), and the read
  refuses a path that is not a regular file down every segment of the commit's tree (a
  symlink, a submodule, a missing entry, a truncated tree) as `not_markdown`.

### Changed

- docs/api.md §6.8: the contract file cap is 4 MiB (was 1 MiB) for a card's section too.
- docs/api.md §16.11: `contract` is a reserved project view, so a project slug or alias
  `contract` stops `maity-hub migrate`, which names the holder to the operator.
