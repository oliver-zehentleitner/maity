### Fixed

- cli: `maity join` flushes the resume text before its closing lines, so
  through a pipe (`2>&1`, as agent harnesses read) the chat line and the
  `pipx ensurepath` sentence come last, as on a terminal; a hand-over
  message id of `true` counts as none named.
