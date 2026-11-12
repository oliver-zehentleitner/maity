### Security

- cli: under the runner, maity takes the clone's `.git` only as the directory
  whose inode the runner recorded when it started the session, opened once
  without following a link, and reads the recorded git and the refs through
  it; git's own repository for each run is made outside the clone, in the
  runner's directory for the agent (for Codex, whose maity runs inside its
  sandbox, it stays in `.git/maity`). Code in a sandbox that allows renaming
  `.git` could otherwise put a directory of its own there and have a program
  run outside the sandbox. Claude Code 2.1.322's sandbox already refuses that
  rename (EBUSY), through a mount the runner does not ask for. Placements
  started before the update need a restart.
