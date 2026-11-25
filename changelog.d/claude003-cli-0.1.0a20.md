### Changed

- cli: version 0.1.0a20 for PyPI. It brings the Codex start and close fix to the runners: a Codex
  start ends the placement's updater loop and stops the app-server daemon left in its codex-home
  first, and a closed placement gets the same steps (#2175, #2207); the other CLI changes since
  0.1.0a19 are in their own entries.
