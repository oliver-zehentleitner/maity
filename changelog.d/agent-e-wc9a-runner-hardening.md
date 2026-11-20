### Security

- cli: the runner's plain-call hook refuses a line that names `maity` and holds a control
  character other than a tab or a newline (a carriage return, a vertical tab, a form feed,
  DEL, C1) or a space other than the ASCII one (a no-break, em, ideographic or other Unicode
  space, U+0085, a zero-width space, U+FEFF). The shell does not split words there, so such a
  line was not held to one plain call before. A line another rule refuses keeps its reason.

### Fixed

- cli: every tmux target of the runner names its session exactly (`-t =name`, and
  `-t =name:` where tmux reads a pane), so a command for a session that is gone no longer
  reaches another session whose name starts with it. The attach hint uses the same form.

### Changed

- docs: `docs/runners.md` says that under agy and opencode the environment variables the
  runner sets are agent-settable too.
