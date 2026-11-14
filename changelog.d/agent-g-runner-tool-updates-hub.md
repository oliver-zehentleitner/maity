### Added

- hub: a runner can report the harness tools it manages and `maity` itself
  (`capabilities.tools`, docs/api.md §15.16); the runner view shows them with the owner's
  open `update_requests`
- hub: `POST /runners/{id}/updates` lets a runner's owner ask for `Update now` on a tool the
  runner updates (`409 conflict`, `updates_off` otherwise); the runner reads open requests
  with `GET /runner`, and a report naming a request it carried out settles it
- hub: status reports accept `reason: updated` with `exited` and a harness's
  `reason: login_needed`
