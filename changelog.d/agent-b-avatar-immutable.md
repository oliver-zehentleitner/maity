### Changed

- hub: a member's picture asked for under its current version (the `v` of its `avatar_url`, at
  any size) is answered `Cache-Control: private, max-age=31536000, immutable`, so a reload of
  the board or a card asks no avatar again. Without `v`, or with any other `v`, it stays
  `private, no-cache`. Who may read a picture is unchanged; the public address keeps its own
  caching.
