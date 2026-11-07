### Added

- `tools/ci_watch.py`: one watcher for every pull request's CI result on an exact head. The author adds
  `<pr> <head sha> <handle#instance>` to its queue file; `run` reports the newest `ci` run of that pull
  request's branch on that head, green or red with the failed jobs, through `maity say`, and removes the line.
  A moved head, a merge, a close or a conflict with main is reported too. It only reads from GitHub.
