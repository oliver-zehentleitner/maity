### Fixed

- cli: `maity runner serve` starts Claude Code in interactive mode again. The runner gave
  `--mcp-config <path>` as two arguments, and Claude Code reads that option's values until the
  next option, so without a `--model` it took the start prompt for a second configuration file
  and exited 1 at once ("MCP config file not found"). The runner now gives
  `--mcp-config=<path>`.
