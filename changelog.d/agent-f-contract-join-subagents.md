### Added

- docs/api.md §3.1, §3.2, §5.2, §6.2: a join has the switch `subagents`, on by default for the
  roles `coder` and `reviewer`. When on, the agent gets its owner's instruction to do every review
  or coding task from Maity in a fresh subagent and to send results with `maity say`: the join's
  `201` carries it as `instruction` for the dashboard to copy with the join line, the join page
  quotes it, and the resume packet carries it beside the briefing as
  `membership.subagents.instruction`, written by the owner; the CLI prints it before the briefing.
  It is written in `subagents_language`, by default the creator's dashboard language, with a
  switch for English in the dialog. Later it is changed only by a caller who could create a
  join for the agent.
