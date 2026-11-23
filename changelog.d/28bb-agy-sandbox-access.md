### Fixed

- cli: an Antigravity (agy) placement's settings now allow reading the Keep the Why skill
  the runner delivers, which agy's documentation says mounts it read-only in agy's sandbox,
  where the skill directory showed up empty before. Writing it stays denied. Not yet
  confirmed in a live session.
- cli: where a link lies above the runner's Keep the Why skill directory (a linked home,
  say), a placement on the runner's own machine now gets the skill's resolved path, in
  `MAITY_KTW_SKILL_DIR` and in every harness's rules for it, so they name the directory
  the sandbox sees. Placements on ssh hosts are unchanged.
