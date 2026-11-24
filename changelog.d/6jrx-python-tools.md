### Added

- runner: `python_tools` in a repository's grant names directories of the
  clone (such as `tools` and `web/tools`) whose scripts a sandboxed Claude
  Code agent may run as `python3 <dir>/<name>.py` with plain arguments,
  from the clone's root. The runner's hook holds such a line to that exact
  form, and refuses it when it cannot check it. Empty by default; not on an
  ssh host. The sandbox stays the boundary.
