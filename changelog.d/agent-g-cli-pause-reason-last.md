### Changed

- cli: the line for a pause (a refused claim, and the note `maity wait` adds) ends with the
  reason, quoted as the human wrote it; before, the reason stood before the command's own
  instruction and could read as part of it. Without a reason the line ends with that
  instruction; "no reason given" is no longer printed.
- cli: a `"` in the reason for a pause or an isolation shows as `\"` and a backslash as `\\`,
  so the reason cannot close its quote and continue as the command's own text.
