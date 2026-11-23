### Changed

- cli: `maity runner install` ends with the next steps in order (complete the configuration, restart, `check` as `maity-runner`, the tools' and the forge's login), and a started service with the login steps (tsk-2k0jcaxfd0ja).
- cli: a `maity runner` command without `--config` whose default file is missing names `/etc/maity-runner/runner.toml` and how to pass it when the service's file exists; it never reads that file in the default's place (tsk-2k0jcaxfd0ja).
