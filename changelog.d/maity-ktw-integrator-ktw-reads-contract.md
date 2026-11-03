### Added
- contract: §11.5, the Keep the Why views' reads: `GET /projects/{owner}/{slug}/keep-the-why/export` and
  `…/keep-the-why/bodies` serve a published export whole, and a lean export's entry texts, for the project's
  family and the public repositories it names (one hop, read with the instance token or none, never an
  owner's grant), through §11.3's forge-only read and cache.

### Changed
- contract: §11.3's cap on one `state.json` is 2 MiB (was 1 MiB).
