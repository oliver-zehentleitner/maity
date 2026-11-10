### Added

- ci: the three database jobs run on a self-hosted runner when the repository variable
  `HUB_RUNNER` is set (labels as JSON); unset, they run on GitHub-hosted runners. A fork's
  code reaches the machine only through the repository's approval setting, which
  `deploy/runner/README.md` states. The database services bind to loopback and their images
  are pinned by digest. Hooks, a system unit and the install steps are in `deploy/runner/`.
