### Added

- cli: `sudo maity runner install <pairing url> --code-file -` sets the runner up as a systemd
  system service in one step. It creates the `maity-runner` user (recorded as install's in
  `/var/lib/maity-runner-install.json`) and its directories, and writes
  `/etc/maity-runner/runner.toml` and the unit, whose `ExecStart` runs this `maity`'s
  interpreter, quoted for systemd. It then pairs as that user, enables the service and runs
  `maity runner check`. The paths are fixed. Anything on them that is not as install would have
  made it (a link, another owner, a directory others can write) stops it before any change.
  While the configuration is not one `serve` would accept, the service is enabled but not
  started. `maity runner uninstall` stops the service and its agents, then removes the unit; if
  it cannot tell that the agents stopped, it removes nothing unless `--force`. `--purge` also
  removes state, workspaces, the configuration and the account install made.
