### Fixed

- cli: on Windows `maity` reads and writes UTF-8 through a pipe, names a state directory in PowerShell form, keeps `./maity-files/` private and its home's environment secret under `%LOCALAPPDATA%`, and its `git` calls no longer take hooks from a `/dev/null` path a user could create.
