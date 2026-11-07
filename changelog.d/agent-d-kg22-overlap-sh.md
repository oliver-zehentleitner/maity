### Added

- tools: `tools/overlap.sh` checks a branch against the open pull requests
  that change the same files. It decides by `git merge-tree`'s exit code in
  any locale, and names a conflict that already exists with `main` without
  counting it. It takes every pull request's files from git, a renamed file
  under both names, and stops with exit 2, never 0, when the check cannot
  run. CONTRIBUTING points to it as the check before a push.
