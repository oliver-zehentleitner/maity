### Changed

- CLI development (`cli/requirements/dev.txt`): the dev tools are pinned with hashes, compiled with the
  hub's dev lock as constraints, so black, ruff, mypy and pytest are the hub's versions. CI's `cli` and
  `cli-windows` jobs, the release workflow's checks and `make -C cli dev` install from it, then the CLI
  editable without build isolation. `make -C cli lock` and `lock-check` cover it, and the audit workflow
  checks it against known advisories.
