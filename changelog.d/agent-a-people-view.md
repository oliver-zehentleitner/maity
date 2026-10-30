### Added

- docs: `GET /people/{handle}` (§6.27), the dashboard's view of a person or an organisation for a signed-in human: `page_served`, the bio while public, the links by `links_visible`, the shared and the public projects with `projects_total`, an organisation's members for its members; a person or organisation that shows the reader nothing is `not_found`.
- docs: `avatar_url` in `GET /people/{handle}` is `null` where §6.10 does not let the caller read the image.
