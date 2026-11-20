### Security

- runner: `maity runner loop` and `maity runner logcap` take only the file the runner wrote for
  them in the agents' user's `~/.maity-runner` (the placement's `loop.json`, its pane log),
  checked on every call, with or without `MAITY_PLACEMENT`; any other path, a link out of it or
  a file others may write is refused. Claude Code, opencode and Antigravity also deny
  `maity runner` in an agent's command rules (security round 5, S201/S202).
