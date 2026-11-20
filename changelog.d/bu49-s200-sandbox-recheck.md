### Changed

- cli: the hook of a placed Claude Code session reads where a line's
  command starts past its leading comment lines and blank lines, as Claude
  Code reads a call; such a line that names `maity` is still refused, now
  with the reason for a `maity` call that is not one plain call.
- cli: the README says what keeps a placed Claude Code session to one plain
  `maity` call: the runner's hook, which refuses a line with a command or
  a wrapper in front of `maity`, not the sandbox's exclusion.
