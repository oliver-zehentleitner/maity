### Changed

- ci: the database jobs go to the self-hosted machine only on a push (to `main`); every pull request runs on a hosted runner, in parallel, so that a queue for the one runner per job type cannot hold up the checks.
