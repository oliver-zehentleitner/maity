### Changed

- docs: `docs/agents.md` states the hook's guarantee as the agreed boundary:
  a line Claude Code may take out of the sandbox runs `maity` only as one
  plain call; names assembled from expansions are left to the sandbox and
  the CLI's own guard.
