### Added

- docs/api.md §11.4: the instance's GitHub App and a human's links to its installations.
  - `MAITY_FORGE_GITHUB_APP_ID`, `…_SLUG`, `…_PRIVATE_KEY`, `…_CLIENT_ID` and `…_CLIENT_SECRET`
    configure the App: all five or none; a partial set stops the hub.
  - `POST /me/forge/github/link` returns the installation page with a single-use `state`.
  - `GET /forge/github/setup` links the installation, only when its account is the user who
    installed it. It always ends on the dashboard's forge settings with a 303, with
    `?error=<reason>` when the link fails; with `Accept: application/json` the reasons come
    back as JSON.
  - `GET /me/forge` and `DELETE /me/forge/github/links/{id}` list and remove links.
  - Installation tokens are minted with the App's key and live in memory only. Migration
    0073 adds `forge_link` and `forge_link_state`.
- docs/api.md §11.4: a human's own forge token as the second source.
  - `PUT /me/forge/github/token` takes only a fine-grained token (`classic_token` otherwise),
    checks it with the forge and stores it sealed with `MAITY_SECRET_KEY`
    (`secret_key_missing` without it). It answers `{configured, login}` and never returns the
    token.
  - `DELETE /me/forge/github/token` removes it.
  - `GET /me/forge` shows `{configured, login, status, checked_at}`. Migration 0073 adds
    `forge_token`.
