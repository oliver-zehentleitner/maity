### Changed

- cli: on macOS the runner switches Claude Code's sandbox on with Seatbelt (`sandbox-exec` on the agents' `PATH`), with the same strict settings as on Linux; `maity runner check` names Claude Code's sandbox on Linux, macOS and other POSIX systems (Windows refuses `maity runner` as before), and `install` on macOS points at `maity runner serve`.

### Security

- cli: the clone check refuses `objects/info/alternates` and `http-alternates` in any case, as a case-insensitive file system (macOS, Windows) hands them to git.
