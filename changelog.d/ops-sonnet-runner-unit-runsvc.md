### Fixed

- ci: the self-hosted runner's systemd unit starts `bin/runsvc.sh` instead of `run.sh`, which
  copies a helper into its own root-owned directory, fails, and made the service exit at once and
  restart in a loop. The README also names the directory for the `chgrp` and the same-named group
  it assumes.
