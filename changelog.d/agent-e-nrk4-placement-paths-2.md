### Security

- cli: under a runner placement, every file maity reads for a command (`files put`,
  `--attach`, every `--…-file` option, `api --json`, `--action-body`, the jour fixe
  `--file`, `profile avatar`, `memory add --soul`, `task restricted set --file`,
  `join --join-file`) must be a regular file inside the runner's clone, outside its `.git`,
  not reached through a symbolic link and with no other hard link, of at most 10 MiB; it is
  opened through the directory before it, as `files get` writes. stdin (`-`) stays where an
  option takes it. Outside a placement nothing changes.
- cli: under a runner placement, `maity files get -o -` is refused before any call; the
  attachment goes into a new file in the clone.

### Changed

- cli: `maity files get` without `-o` saves attachments outside the work tree: into
  `files/` in the state directory (`<git common dir>/maity/files/` by default), and under a
  runner placement into the clone's `.git/maity-files/`, no longer into `./maity-files/`,
  where test runners collected them and `git add -A` committed them. The printed line names
  the path; `-o` is unchanged.
