### Changed

- cli: the hook of a placed Claude Code session reads where a line's
  command starts past its leading comment lines and blank lines, as Claude
  Code reads a call; such a line that names `maity` is still refused, now
  with the reason for a `maity` call that is not one plain call.
