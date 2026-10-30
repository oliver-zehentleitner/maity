### Removed

- cli: the compatibility layers for older hubs and states before launch: the `openapi.json` lookup on a 404
  (also for `maity chat cnv-…`, `maity ticker post` and the runner's pickup), the resume resent without
  `environment` or `supervisor`, `GET /me` for a state holding only the slug, the single-role fallback without
  `trust`, and the refusal of a card without a `links` list; docs/api.md §13 and §17.6 drop the matching text.
  The `not_found` follow of a moved project through `GET /me` stays
