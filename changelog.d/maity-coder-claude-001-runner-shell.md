### Fixed

- cli: every session the runner starts now gets `SHELL` (`/bin/bash` where the host has
  it, else `/bin/sh`), for every harness and on ssh hosts too. Without it tmux handed each
  session the account's login shell, `/usr/sbin/nologin` for the service account
  `maity runner install` makes, so an OpenCode placement's every command failed with "This
  account is currently not available." and the agent never checked in. The account's login
  shell stays nologin. A tmux server an older runner started gives a new session the shell
  as well, so restarting the affected placements is enough.
- cli: `maity runner check` names the `SHELL` sessions get, here and on each ssh host, and
  reports an error when it is, or links to, nologin or false.
