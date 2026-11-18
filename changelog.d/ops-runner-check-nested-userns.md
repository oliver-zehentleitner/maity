### Added

- cli: `maity runner check` (local backend) starts a user namespace inside bubblewrap as the agents' user
  and reports an error only where the mapping is refused (Ubuntu's AppArmor profile
  `bwrap-userns-restrict`): Claude Code's sandbox then starts, but every sandboxed command,
  a subagent's included, fails on its seccomp step. docs/runners.md, "Ubuntu: nested user
  namespaces", names the cause and the host-side options.
