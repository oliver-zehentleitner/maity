### Security

- cli: a Claude Code placement's sandbox now hides a scratch made after the
  session started. Before, it was denied only the other scratches that existed
  at its start, so a later placement's scratch stayed readable from it,
  including that placement's task output where its own `tmp` was the
  `TMPDIR`. The sandbox now denies its own project's `.scratch` for reading
  only and opens the placement's own scratch again. Every other project's
  `.scratch` is denied whole. A project with no `.scratch` yet at the start is
  not covered. Like the private `TMPDIR`, this reaches only Claude Code
  placements started after the upgrade, so restart each one.
