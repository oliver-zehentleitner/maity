### Fixed

- cli: under a runner placement, `maity say --type review_result` checks the review's
  cites in the runner's clone, whatever directory the agent works in. An agy session
  works in the workspace folder that holds the clone as `repo`; the check found no
  clone there and sent the review unchecked.
  Under a placement whose clone cannot be named (`GIT_COMMON_DIR` missing or not a
  clone's `.git`), the review is refused and nothing is sent; it is no longer checked
  from the current directory instead.
