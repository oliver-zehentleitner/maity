### Changed

- ci: the self-hosted runner is one service per database job type (`maity-runner@sqlite`, `@pg`,
  `@maria`, labels `<prefix>-sqlite|pg|maria`), selected by the repository variable
  `HUB_RUNNER_LABEL` (replaces `HUB_RUNNER`), so a pull request's three jobs run side by side and no
  two Postgres jobs share the host port. Each service runs the suite with `-n 3`.
  `deploy/runner/install-services.sh` installs them; hosted runs and fork pull requests are unchanged.
