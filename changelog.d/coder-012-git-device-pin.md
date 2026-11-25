### Security

- cli: under the runner, maity takes the clone's `.git` only as the
  directory whose device and inode the runner recorded at the session's
  start (`MAITY_GIT_DEVICE` beside `MAITY_GIT_INODE`), no longer by the
  inode alone. A session started by an older runner runs no maity git
  until the placement is restarted.
