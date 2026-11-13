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
- cli: every status line and every `maity:` message on stderr is printed
  cleaned, so the ids, statuses and texts the hub returns in them (the
  release summary and checklist, claim, ask, answer, say, the attachment ids
  after a failed send) cannot act on the terminal; `--json` keeps the data.
