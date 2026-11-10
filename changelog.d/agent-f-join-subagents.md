### Added

- Hub, CLI and dashboard: the join option `subagents` (docs/api.md §3.1). A join for a `coder` or
  `reviewer` carries its owner's instruction to do every review or coding task from Maity in a
  fresh subagent, unless the human unticks "Use subagents" in the join dialog; the dialog can
  write it in English instead of the dashboard's language, shows it above the paste line and
  copies it with the line. The join page quotes it, the resume packet carries it as
  `membership.subagents`, and `maity join` and `maity resume` print it right before the briefing.
  The owner changes it with `PATCH …/members/{id}` under the join's rules (`join_rule`). The
  migration gives coder and reviewer members and open joins from before it the instruction,
  set by the agent's owner in that human's language.
