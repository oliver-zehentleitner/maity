### Security

- cli: text from the hub and from GitHub is printed cleaned: hub error codes and
  messages, a text answer of `maity api`, `maity help`, the project, member,
  credential and attached-project names a join or a runner pairing prints, and
  `maity gh pr view` show terminal escape sequences and other control characters
  as visible escapes instead of passing them to the terminal.
- cli: `maity join --pointer` does not write into an `AGENTS.md` or `CLAUDE.md`
  that is a symbolic link (one linked to this `AGENTS.md` excepted) or no
  regular file, and opens both in the repository's root directory opened once;
  for a file it refuses or cannot write it prints the block instead.
- cli: the attachment ids `maity say --attach` names after a failed send are
  printed cleaned.
