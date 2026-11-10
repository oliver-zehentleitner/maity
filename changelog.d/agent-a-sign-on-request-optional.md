### Changed

- docs/api.md §2.2: the `Maity-On-Request` line is part of the canonical string only when the
  header is sent; without it the string keeps its seven lines, so requests sign as before and hub
  and CLI can ship independently (#419 had added it as an empty line to every request).
