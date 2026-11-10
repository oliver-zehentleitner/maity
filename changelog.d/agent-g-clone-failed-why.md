### Fixed

- cli runner: a failed clone now says why in the runner's log (`<placement>: clone_failed:
  <why>`). The reason is maity's own message when git could not run (not found, refused by the
  clone check, timed out), or git's last line of output. The report to the hub keeps only the
  codes.
