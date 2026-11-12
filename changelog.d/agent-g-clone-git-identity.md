### Security

- cli: under the runner, maity takes the clone's `.git` only as the directory
  whose inode the runner recorded when it started the session, opened once and
  read through that descriptor. Sandboxed code could rename `.git` and put a
  directory of its own there, whose recorded git maity then ran outside the
  sandbox. Placements started before the update need a restart.
