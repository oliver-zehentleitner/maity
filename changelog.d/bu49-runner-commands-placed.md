### Security

- cli: in a placed Claude Code session, the hook refuses a line in which a
  word `runner` follows a word `maity`, and a line that names `maity` and
  holds a comment, a heredoc or more than one line; `maity runner` is the
  runner's own command (tsk-54492gk4xp69, part 1). A line with
  assignments to `MAITY_WAIT_TIMEOUT`, `NO_COLOR`, `LANG`, `LC_*` or
  `TZ` before `maity` is held to one plain call like one whose first
  word is `maity`; anything else before a word `maity` (an assignment to
  any other name, the runner's own `MAITY_` variables included, or with
  `+=`, another command, a keyword, `!`, a
  redirection, a subshell or a group, or `maity` by a path) refuses the
  line, text that mentions `maity` after another command included
  (`--body-file` is the way out). A word counts as `maity` or `runner`
  also once the backslashes and quotes in it are taken off, a word with
  a brace also as each of its alternatives and as each word its brace
  expansion makes, a word whose braces make more than 256 words refuses
  the line, and a line
  with `$'…'` text that holds a backslash or with `$"…"` is refused. A
  quoted or escaped first word before `maity` (`"[" maity status`)
  refuses the line like any other word before it.
