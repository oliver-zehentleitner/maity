### Added

- web: **where the agents run** (docs/api.md §15.5–§15.7): a section of the Agents view with one row
  per placement — runner, harness, model and mode, wanted state, the runner's reported state in
  words (crash loop with its count, retry time, waiting for the runner on a new generation), the
  generation — and **Stop**, **Start**, **Restart** (confirmed) and **Restart with a new join**
  (only where the credential was revoked) for the runner's owner with members:admin or the agent's
  owner; a pending consent links to its inbox request; refusals show the hub's message and code;
  placement events read the list again
