### Security

- cli: `maity runner` holds a placed Claude Code agent's `maity` command to one plain
  call under the harness's sandbox: a hook the runner writes into the session's settings
  refuses a line that starts with `maity` and pipes, chains, redirects, sends it to the
  background, substitutes or holds a heredoc, a newline or a `$`, and refuses the call when
  it fails itself. opencode's rules refuse the same lines.
