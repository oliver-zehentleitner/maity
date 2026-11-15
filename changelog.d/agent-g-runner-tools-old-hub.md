### Fixed

- CLI: a runner that manages no tool (no `install` or `update` under
  `[harness.<id>]`) no longer reports `tools` to the hub, so it keeps
  working with a hub from before 0.1.0a8, which refuses the field and
  would stop the runner at its start. Managing a tool needs hub 0.1.0a8
  or later.
