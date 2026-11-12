### Fixed

- cli: an interactive placement no longer tells the hub it is supervised
  (`MAITY_SUPERVISOR` only for a supervised one), so it waits for the next
  event with `maity wait` instead of ending its turn and missing later
  messages.
- cli: git in a runner's sandboxed session (Claude Code, Codex) works without writing
  `.git/config`: the session gets `branch.autoSetupMerge=false`,
  `push.default=current` and `fetch.recurseSubmodules=false`, and the start
  prompt of Claude Code and Codex names the commands that still fail
  (`push -u` and `--set-upstream`, which push but cannot store an upstream,
  `--track`, and `branch -m`, which renames and then fails).
- cli: `maity report` reads a branch without an upstream as its own branch on
  the push remote (`branch.<b>.pushRemote`, `remote.pushDefault`, else
  `origin`) instead of refusing it, unless a `pushurl`, a `push` refspec or a
  `pushInsteadOf` could send the push elsewhere.
- cli: the runner hides the placeholders Claude Code's sandbox puts into the
  work tree in the clone's `.git/info/exclude`, only for paths that are missing
  or an empty directory at the start.
- cli: a repository grant's `pull_requests = true` lets placed agents open and
  read pull requests with `maity gh pr create` and `maity gh pr view`, always
  on their own clone's repository (a body file is read in the clone only; on
  Windows `--body` only). Without `--json`, `pr view` asks gh for fixed fields and
  prints them as text, so it also works with an older gh whose own text view the
  forge refuses. The grant and the body file are read through the
  `.git` the runner recorded at the start: a `.git` renamed or replaced in the
  session is refused. Under the harness's sandbox no placed session runs
  gh itself. A gh entry in a grant's `allow` is ignored, and
  `maity runner check` warns about it. Codex is refused for a repository whose
  grant has `allow` or `pull_requests`.
- cli: in a runner's placement, `maity` that cannot read the clone's credential
  (Claude Code's sandbox hides it from a pipe or a chained command) says to run
  maity alone instead of "has not joined a project", and the Claude Code start
  prompt says so too.
