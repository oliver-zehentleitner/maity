### Changed

- cli: version 0.1.0a16 for PyPI. A placement's scratch now sits beside
  its clone and is removed when the placement closes (#1917). Codex keeps
  its `CODEX_HOME` inside that placement scratch, outside the hidden state
  directory, so its exec helper runs (#1979). An Antigravity placement
  gets a writable scratch under the host's shared temp directory when the
  beside-clone one is read-only (#1994). A Claude Code subagent's leftover
  worktree under the clone is cleared by a git-free prune on every
  placement start, so the clone reads as plain again (#2003). The runner
  disables Claude Code's background-shell pressure reaper per placement, so
  a low-memory moment no longer kills a placement's background `maity wait`
  (#1977). The opencode adapter uses the configured default model and fails
  closed when the model is unknown, instead of sending the repository to a
  hosted default (#1969). `maity runner check` warns that opencode has no
  OS sandbox under the `single` layout (#1963) and starts a nested user
  namespace inside bubblewrap so the sandbox check matches how placements
  run (#1949). The clone check tolerates the sandbox's empty
  `.git/config.lock` (#1954). The advertised running count survives a
  reconnect (#1950). Plain-call hook docs and test inputs are corrected
  (#1973). `maity placement stop` and `restart` take an
  `<agent>#<instance>` and refuse an agent that runs on several
  placements, naming their ids; `maity placement list` shows
  `<handle>#<instance>` (#1938).
