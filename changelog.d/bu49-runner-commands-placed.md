### Security

- cli: in a placed Claude Code session, the hook refuses a line in which a
  word `runner` follows a word `maity`, and a line that names `maity` and
  holds a comment, a heredoc or more than one line; `maity runner` is the
  runner's own command (tsk-54492gk4xp69, part 1). A `maity` line after
  variable assignments or a command such as `env`, `nice` or `sudo` is
  held to one plain call like one that starts with `maity`.
