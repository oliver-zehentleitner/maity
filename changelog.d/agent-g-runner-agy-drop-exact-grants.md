### Changed

- cli: exact command grants (an `allow` entry without a trailing ` *`) are no
  longer applied to antigravity (agy) placements; agy does not match them the
  way Claude Code does, so such an entry now runs inside agy's sandbox like an
  unlisted command, and `maity runner check` names it. This narrows agy
  grants: a placement that relied on an exact grant running outside agy's
  sandbox must grant it with a trailing ` *` (`make test *`) or arrange the
  work another way. Grants ending in ` *`, and the `allow` list for Claude
  Code and Codex, are unchanged.
