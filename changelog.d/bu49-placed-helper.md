### Security

- cli: an empty or malformed `MAITY_PLACEMENT` now counts as a placed session
  and is refused: maity runs no git for it, and `maity runner loop` and
  `maity runner logcap` take no placement's file under it. One helper in
  `clonecheck` now decides whether a session is placed, and the placement id
  pattern lives there too.
