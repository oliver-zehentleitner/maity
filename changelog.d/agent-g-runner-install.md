### Added

- cli: `sudo maity runner install <pairing url> --code-file -` sets the runner up as a systemd
  system service in one step. It creates the `maity-runner` user (marked as install's) and its
  directories, and writes `/etc/maity-runner/runner.toml` and the unit, whose `ExecStart` runs
  this `maity`'s interpreter, quoted for systemd. It then pairs as that user, enables the
  service and runs `maity runner check`. As root it never follows a link in the service
  user's directories or at a file it writes. While the configuration is not one `serve` would
  accept, the service is enabled but not started. `maity runner uninstall` stops the service
  and its agents, then removes the unit; if stopping fails it removes nothing unless
  `--force`. `--purge` also removes state, workspaces, the configuration and the account
  install made.
