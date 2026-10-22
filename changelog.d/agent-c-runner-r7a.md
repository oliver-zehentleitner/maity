### Added

- cli: the runner's `agent_user` layout (runner slice R7a, design v2 §7.6) — with
  `layout = "agent_user"`, the tmux server, clones, joins, the supervised loop and `gc` run
  as `sudo -n -u <agent_user> --` with only the environment they need; the agents' files
  live in `~<agent_user>/.maity-runner/`; the runner's state and credential stay out of the
  agents' reach; capabilities say `runner_separate: true`; `maity runner check` tests sudo,
  `maity` as the agents' user, and the workspaces' write access.
