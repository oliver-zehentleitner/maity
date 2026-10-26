### Fixed

- web: a visitor's call with a query (the device sign-in's `?wait=0`) is no longer taken for a
  session's own call, so a 401 on it does not show "Your session has ended"
