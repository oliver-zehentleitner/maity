### Fixed

- ci: the `hub-contract` job also runs when a pull request changes `cli/src/maity/runner/capabilities.py`, which
  `hub/tests/test_runner_confinement.py` checks the hub against; a change to that file alone left the job skipped, so a
  confinement the hub refuses was found only on main.
