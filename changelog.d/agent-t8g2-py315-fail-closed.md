### Fixed

- cli: on Python 3.14 and later the runner refuses a start again when it cannot list another
  clone's credential or another placement's scratch completely (a place behind a link into a
  directory the agents' user cannot search, or a project it cannot search). pathlib's
  `is_dir()` and `is_symlink()` answer False there instead of raising, so on the runner's own
  side the listing skipped what it could not see. The sandbox then started without the deny
  for it. The listings now decide with `os.stat`/`os.lstat`, so every error other than
  "nothing there" refuses the start, on every Python.
- cli: the same for the check of Claude Code's managed and user settings (the hook and socket
  checks). On Python 3.14+ a settings file below a directory the runner cannot search passed
  for absent; it is now named as one that cannot be checked.

### Changed

- ci: the cli job also runs on Python 3.14 and 3.15 (cli-windows stays on 3.11 and 3.13).
