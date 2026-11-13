### Fixed

- cli: under the runner, a clone in which a sandboxed Claude Code session ran is no longer refused as "not a plain clone" for the empty `.git/glab-cli/`, `.git/modules/` and `.git/worktrees/` the sandbox makes to guard paths it protects. Before, every placed Claude Code session broke `maity checkpoint`, `maity report` and the runner's next start in its own clone. With anything in them they are refused as before (`modules/` as submodules, `worktrees/` as worktrees).
