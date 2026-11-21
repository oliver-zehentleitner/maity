### Fixed

- cli: `maity gh pr edit` sets the title and the body with one REST call
  through gh (`gh api --method=PATCH` on the pull request of the clone's
  own repository) instead of `gh pr edit`, which in older gh versions
  asks the forge for `projectCards` (Projects classic) and failed without
  setting anything. A branch is first turned into its pull request's
  number; maity prints which pull request changed, as one line.
