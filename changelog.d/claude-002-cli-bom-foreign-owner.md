### Fixed

- cli: a leading byte order mark is dropped from every text read from stdin
  or a file (`-`, `--body-file`, `--file`, `--review-file`), not only from
  `--join-file`; PowerShell and Notepad write one.
- cli: a state directory or file that belongs to another user is refused with
  the way out (revoke the session, or give the agent a directory of its own)
  and, when others can reach it too, who they are, on Windows and POSIX alike.
