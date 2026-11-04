### Fixed

- web: a public project's `/overview` and `/overview/project` show its public overview, read-only,
  to a visitor and to a signed-in non-member, so the badge's link no longer ends on the login or on
  `not_member`; `/overview/swarm` stays the login for a visitor and takes a signed-in non-member
  to `/overview` (docs/api.md §16.9, §16.11).
- docs/api.md §1.1, §16.13: the pages with the product line allow its one `<style>` block by a
  `style-src 'sha256-…'` hash.
