### Fixed

- ci: the self-hosted runner's systemd unit starts `bin/runsvc.sh` instead of `run.sh`, which
  copies a helper into its own root-owned directory, fails, and made the service exit at once and
  restart in a loop. The README also names the directory for the `chgrp` and the same-named group
  it assumes.
- ci: the three database jobs print the runner's name, environment and CPU count first, so a log
  shows whether a run was hosted or on the maintainer's machine.
- ci: `deploy/runner/install-python.sh` gives the self-hosted runner a Python 3.12 that
  `setup-python` finds (it has none for Debian), without the PEP 668 marker and with a plain `.path`.
