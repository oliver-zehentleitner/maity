### Added

- docs/api.md §6.8: `GET /projects/{owner}/{slug}/contract` — the project's contract file read
  whole through the probe, with a table of contents and an anchor per heading, under an `ETag`;
  `settings.contract_path` (§6.1, default `docs/api.md`) names the file; a dashboard view
  `/<owner>/<slug>/contract` (§16.11) and the overview's contract row link it (§6.11).

### Changed

- docs/api.md §6.8: the contract file cap is 4 MiB (was 1 MiB) for a card's section too.
