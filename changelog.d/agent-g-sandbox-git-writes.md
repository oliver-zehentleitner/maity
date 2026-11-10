### Fixed

- cli runner: a Claude Code agent with the sandbox on can fetch, commit and push again. The runner
  denied edits to all of the clone's `.git`, and the sandbox turned that into a read-only `.git`
  for every command, so `git fetch` failed on `.git/FETCH_HEAD`. The deny now names only
  `config`, `config.worktree`, `hooks/`, `info/`, `objects/info/alternates` and `.git/maity`.
- cli: maity's git check of a runner's clone accepts the empty placeholders Claude Code's sandbox
  leaves in `.git` (`config.worktree`, `objects/info/alternates` and `http-alternates`, `remotes/`,
  `.claude-sandbox-noreplace/` anywhere in `.git`). A placement whose session ran sandboxed no longer refuses its
  own clone at the next start. Any of them with content is refused as before.

### Added

- cli runner: at each start the runner reads an existing clone with the same check before the
  join and the harness, and starts nothing in one whose `.git` is not a plain clone's, such as
  a `commondir` or `worktrees/` an earlier session wrote. The placement fails with
  `workspace_in_use` and the detail `not_a_plain_clone`; the runner's log names what it found,
  and nothing in the clone is removed.
- contract, hub: §15.7 lists `not_a_plain_clone` as a detail of `workspace_in_use`, and the hub
  takes it in a runner's report. Deploy the hub before a runner with this check: an older hub
  answers a report with the new detail `400 invalid`.
