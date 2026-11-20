### Fixed

- cli: under a Codex placement, a file in the placement's scratch is read for
  `--body-file`, `--review-file`, `--attach` and the other file flags. maity
  refused every one ("the way to the placement's scratch (…) is not plain
  directories") because it opened each directory above the scratch for
  reading, and Codex's sandbox hides the workspaces root and `.scratch` from
  reading. On Linux maity now only passes through those directories, without
  following a link, as before; the file checks are unchanged.
