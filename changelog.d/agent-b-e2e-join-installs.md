### Changed

- CI (`web-e2e`, `join-smoke`): the hub is installed from its hashed locks and Playwright from the
  new `web/requirements/e2e.txt` (compiled with the hub's runtime pins as constraints;
  `make -C web lock` and `make -C web lock-check`, which `web-e2e` runs first); the CLI goes into an
  environment of its own from `cli/requirements/release.txt`; both are installed editable without
  build isolation. The audit workflow checks the new lock against known advisories.
