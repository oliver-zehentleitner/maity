### Changed

- cli: exact command grants (an `allow` entry without a trailing ` *`) are not
  applied to antigravity (agy) placements; agy does not match them the way
  Claude Code does, so such an entry runs inside agy's sandbox like an unlisted
  command, and `maity runner check` names it. The `allow` list is unchanged for
  Claude Code and Codex.
