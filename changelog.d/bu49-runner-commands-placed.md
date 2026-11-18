### Security

- cli: in a placed Claude Code session, the hook refuses a line in which a
  word `runner` follows a word `maity`, and a line that names `maity` and
  holds a comment, a heredoc or more than one line; `maity runner` is the
  runner's own command (tsk-54492gk4xp69, part 1). A line with variable
  assignments before `maity` is held to one plain call like one that
  starts with `maity`; anything else before a word `maity` (another
  command, a keyword, `!`, a redirection, a subshell or a group, or
  `maity` by a path) refuses the line, text that mentions `maity` after
  another command included (`--body-file` is the way out).
