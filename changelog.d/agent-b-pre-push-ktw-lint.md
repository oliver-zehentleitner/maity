### Changed

- `tools/hooks/pre-push`: the opt-in hook also runs `ktw-lint` for each Keep the Why project a push touches (the
  root, `hub/`, `cli/`, `web/`), and refuses when the installed `ktw-lint` is not the version CI pins, naming both
  versions and the install command.
