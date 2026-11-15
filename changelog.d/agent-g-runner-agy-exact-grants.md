### Changed

- cli: an antigravity (agy) placement gets a repository's `allow` entries
  exactly, as a Claude Code placement does: an entry without `*` is allowed
  with a deny rule for the same command with more arguments, which agy
  refuses when they hold anything but blanks (line breaks inside an argument
  included). agy cannot tell an extra empty argument apart; it is allowed:
  it drops an argument that is empty or only spaces, tabs or line breaks
  (`''`, `""`, `' '`) before it matches, so `make test ''` runs as
  `make test`; `maity runner check` says so for each repository with exact
  entries for agy. An exact entry agy cannot be given exactly (a word with a
  character outside letters, digits and `_ / = : @ % , -`, or an entry
  another entry extends) is left out for agy, runs in its sandbox like an
  unlisted command, and is named by `maity runner check`. Entries ending in
  ` *` stay prefixes.
