### Added

- tools: `tools/overlap.sh` checks a branch against the open pull requests
  that change the same files. It decides by `git merge-tree`'s exit code in
  any locale, and names a conflict that already exists with `main` without
  counting it. CONTRIBUTING points to it as the check before a push.
