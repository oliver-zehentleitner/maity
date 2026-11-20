### Security

- cli: on Linux, `maity runner` starts a sandboxed Claude Code placement only on a machine
  Claude Code supports its seccomp step on (x64 or arm64, from `uname -m`) and a kernel with
  seccomp filtering (`Seccomp:`, and from Linux 5.9 `Seccomp_filters:`, in
  `/proc/self/status`), read as the agents' user; otherwise, or when that cannot be read, the
  start is refused (`failed`, `harness_refused`, the reason in the log). Claude Code shows
  nothing when the step that blocks Unix sockets is off. `maity runner check` reports the
  same, locally and on each ssh host, and then runs the installed Claude Code once headless
  (one small prompt on the agents' login) to see that the step is applied; anything else is
  an error. Run `check` after every Claude Code version change: `check` keeps the version
  whose probe passed, and a start with another installed version logs a warning to run it
  (the start goes ahead). The placement pins its Unix socket settings
  (`sandbox.network.allowAllUnixSockets` off) and refuses user settings that would change
  them: while the agents' user's `~/.claude/settings.json` carries
  `sandbox.network.allowAllUnixSockets`, `sandbox.network.allowUnixSockets` or
  `sandbox.seccompConfig`, or cannot be read, sandboxed Claude Code starts are refused and
  `check` reports an error. docs/runners.md, "Claude Code: Unix socket blocking".
- docs: docs/runners.md states that an agy placement's scratch can be read and written by
  every other agy placement of the same agents' user on the host, and that opencode, which
  has no OS sandbox, reaches other placements' scratch directories and sockets: neither is a
  boundary between placements on one host.
