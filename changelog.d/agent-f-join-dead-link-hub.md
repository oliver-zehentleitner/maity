### Fixed

- hub: a dead join link opened in a browser on the public host (`/join/{token}`) shows the page
  "This join link no longer works" (404, `Maity-Error: not_found`) instead of the JSON error, as
  on the join host; `GET /api/v1/join/{token}` keeps the JSON error unless HTML is asked for
  (docs/api.md §3.2).
