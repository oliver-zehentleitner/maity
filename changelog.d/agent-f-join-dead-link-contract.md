### Changed

- docs/api.md §3.2: a dead join link (unknown, used, expired, burned or revoked token) at
  `GET /join/{token}` on the public host is the page that says the link no longer works, as on
  the join host (§1.1): 404 with `Maity-Error: not_found`, HTML for a browser, Markdown
  otherwise. `GET /api/v1/join/{token}` keeps the JSON error envelope unless the client asks for
  `text/html`.
