### Added

- cli: the runner's ssh backend (runner slice R7b, design v2 §5.4) — `[backend] kind =
  "ssh"` with `[backend.ssh]` (`known_hosts`, `identity`) and `[[backend.ssh.hosts]]`
  (`name`, `address`, `user`, `port`, `workspaces`, `max_agents`, `agent_path`); one target
  per host, each command a quoted fixed template over a shared connection with strict host
  keys and no forwarding; clones, joins (the host's own `maity`) and tmux on the host;
  workspace records keyed by host; a placement's `target` is honoured, `target: null` is
  placed on the first reachable host with a free slot and kept there, an unknown target is
  `harness_refused`/`target_unknown`; an unreachable host keeps its agents' last state and
  is advertised `reachable: false` with `unreachable_since`; `maity runner check [--target]`
  checks each host; `logs` and `stop-all` work across the hosts.
