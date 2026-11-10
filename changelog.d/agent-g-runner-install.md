### Added

- cli: `sudo maity runner install <pairing url> --code-file -` sets the runner up as a systemd
  system service in one step. It creates the `maity-runner` user (recorded as install's in
  `/var/lib/maity-runner-install.json`) and its directories, and writes
  `/etc/maity-runner/runner.toml` and the unit, whose `ExecStart` runs this `maity`'s
  interpreter, quoted for systemd. It then pairs as that user, enables the service and runs
  `maity runner check`. The paths are fixed; the `workspaces` a kept configuration names are not
  checked. Anything on them that is not as install would have made it (a link, another owner, a
  directory or a file of root's that others can write) stops it before any change; a mode that
  only differs from install's is set back.
  While the configuration is not one `serve` would accept, the service is enabled but not
  started. `maity runner uninstall` stops the service and its agents, then removes the unit; if
  it cannot tell that the agents stopped, it removes nothing unless `--force`, and what it can
  know beforehand is checked before the service is disabled. `--purge` also
  removes state, workspaces, the configuration and the account install made.

### Fixed

- cli: the shipped `maity-runner.service` lists `/tmp` in `ReadWritePaths`. `ProtectSystem=strict`
  had left it read-only, so a harness that writes its own files under `/tmp` failed at start.
