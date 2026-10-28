### Added

- ci: the three database jobs run on a self-hosted runner when the repository variable
  `HUB_RUNNER` is set (labels as JSON); unset, and for every pull request from a fork,
  they run on GitHub-hosted runners. Hooks, a user unit and the install steps are in
  `deploy/runner/`.
