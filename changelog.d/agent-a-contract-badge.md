### Added

- docs/api.md §6.20: the project badge — `GET /badge/{slug}.svg`, public and
  served at the root outside the API, `image/svg+xml` with a 60 s public cache
  and an `ETag`; opt-in per project through the policy field `badge` (`off` by
  default, `members` or `agents_online`, §6.1), `not_found` while off, for an
  unknown slug and for a closed project; counts only, never names, rendered
  from `web/brand/maity-badge-template.svg` as `web/brand/BADGE.md` specifies;
  the Markdown snippet with a preview and variant picker on the overview page
  (§6.11); the §12 index row.
