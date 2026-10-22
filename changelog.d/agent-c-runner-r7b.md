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
- cli runner (ssh): the sandbox read denies are worked out per host (the remote user's home
  secrets, its `~/.maity-runner`, the other clones' credentials listed over ssh, failing
  closed on a partial listing) and Codex's sandbox is tried on the host; connections never
  read the operator's terminal, keep alive, ignore the operator's forwarding and local
  commands, and need a ControlPath directory the runner now creates; a remote home that is
  not a plain path refuses the host, and the attach hint is quoted word by word.
- cli runner (ssh): `check` counts the 17 bytes ssh adds to the ControlPath while it binds
  the connection socket, so a `state_dir` too long for it is reported instead of every host
  showing as unreachable; a host's rate-limited placement keeps its slot on that host and
  its limit file is read there.
