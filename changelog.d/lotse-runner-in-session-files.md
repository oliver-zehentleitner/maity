### Security

- runner: `maity runner loop` and `maity runner logcap` take only the file the runner wrote for
  them in the agents' user's `~/.maity-runner` (the placement's `loop.json`, its pane log),
  written as exactly that path with no link on the way, checked on every call, with or without
  `MAITY_PLACEMENT`; any other path, a link, a hard link, another placement's file or a file
  others may write is refused, as is `maity --for … runner`. On an ssh host the runner now makes
  the pane log before logcap starts. Claude Code's sandbox also denies writes to the runner's
  private paths, and Claude Code, opencode and Antigravity deny `maity runner` in an agent's
  command rules (security round 5, S201/S202).
