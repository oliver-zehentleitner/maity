### Added

- hub: `GET /projects/{owner}/{slug}/members/{id}/briefing`: what an agent is told, for its owner and humans with `members:admin`, each part only as far as the caller may read it (§19.3.1).

### Fixed

- hub: `POST /requests/{id}/answer` refuses `on_behalf_of` with `proxy_only` instead of dropping it (§2.3).
