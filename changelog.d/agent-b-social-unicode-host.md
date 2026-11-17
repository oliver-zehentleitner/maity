### Fixed

- hub: a person's Mastodon name or Bluesky handle with a character outside
  ASCII is refused (`format`) before it is lower-cased; a host or handle with
  U+212A (KELVIN SIGN) was stored as its ASCII lower-case, `k` (docs/api.md
  §16.9).
- web: the fixture hub refuses a non-ASCII website host, Mastodon name or
  Bluesky handle before lower-casing, as the hub does.
