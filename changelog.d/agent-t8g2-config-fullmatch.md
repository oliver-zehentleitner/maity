### Fixed

- cli: the runner's configuration check matches every value whole. Ssh host names,
  addresses, users, workspaces and agent paths, and projects, ending in a newline used to
  pass a `^…$` check with `re.match`. They then made the hub refuse the whole hello, which
  stops the runner, or reached the ssh command line. They are refused at load now, with a
  message naming the field. The same holds for a remote home and a tool version the runner
  checks.
