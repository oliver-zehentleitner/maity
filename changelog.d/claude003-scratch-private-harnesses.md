### Security

- cli: on Linux, `maity runner` starts a sandboxed Claude Code placement only on a machine
  Claude Code supports its seccomp step on (x64 or arm64, from `uname -m`) and a kernel with
  seccomp filtering (`Seccomp:`, and from Linux 5.9 `Seccomp_filters:`, in
  `/proc/self/status`), read as the agents' user; otherwise, or when that cannot be read, the
  start is refused (`failed`, `harness_refused`, the reason in the log). Claude Code shows
  nothing when the step that blocks Unix sockets is off. `maity runner check` reports the
  same, locally and on each ssh host, and then runs the installed Claude Code once headless
  (one small prompt on the agents' login) to see that the step is applied; anything else is
  an error. Run `check` after every Claude Code version change. docs/runners.md, "Claude
  Code: Unix socket blocking".
