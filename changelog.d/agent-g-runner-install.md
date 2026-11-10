### Added

- cli: `sudo maity runner install <pairing url> --code-file -` sets the runner up as a systemd
  system service in one step. It creates the `maity-runner` user and its directories, and
  writes `/etc/maity-runner/runner.toml` and the unit, which starts the `maity` that ran the
  command. It then pairs as that user, enables the service and runs `maity runner check`. While
  the configuration still lacks `[limits]` or a harness, the service is enabled but not
  started. `maity runner uninstall` stops the service, ends its agents and removes the unit;
  `--purge` also removes state, workspaces, the configuration and the user.
