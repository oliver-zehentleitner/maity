### Changed

- cli: an antigravity (agy) placement gets a repository's `allow` entries
  exactly, as a Claude Code placement does: an entry without `*` is allowed
  with a deny rule for the same command with more arguments, which agy
  refuses. An exact entry agy cannot be given exactly (a word with a
  character outside letters, digits and `_ / = : @ % , -`, or an entry
  another entry extends) is left out for agy, runs in its sandbox like an
  unlisted command, and is named by `maity runner check`. Entries ending in
  ` *` stay prefixes.
