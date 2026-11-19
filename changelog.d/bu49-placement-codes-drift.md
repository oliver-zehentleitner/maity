### Fixed

- hub: a runner's report takes the details `target_unknown`, `workspace_in_repository`
  and `workspace_not_bare` and the reasons `network`, `context_full`, `auth` and
  `harness_config` that docs/api.md §15.7 already lists; until now the hub answered
  `invalid` to them (tsk-m1mkmx0ncckr). A hub test reads §15.7's two tables and keeps
  the hub's lists equal to the contract.
