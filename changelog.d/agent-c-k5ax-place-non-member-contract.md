### Changed

- contract: `POST …/placements` with `{"agent": {"id"}}` may name a profile of the calling
  human's own that is not a member of the project yet, so a profile made alone (`POST /agents`)
  is placed without a join line first. The caller needs the right to create a join for it
  (`members:admin`, or trust `member` under `policy.member_agents` with a runner already
  attached) and owns the runner; the join fields (`trust`, `role`, `reports_to`, `areas`,
  `capabilities`, `briefing`, `subagents`, `subagents_language`, the last two now for a
  new-profile placement too) are validated as for a first join, the placement counts as the
  profile's open first join, and the pickup is that first join (`creator_lacks_authority`,
  `project_not_allowed`). A profile that is a member by the exchange (joined by a line, or
  another such placement was picked up first) gets a further instance within `max_instances`,
  `instance_quota` beyond it. Removing a membership also closes the project's placements of
  that profile that hold no credential yet. An agent caller still gets `not_a_member`, and a
  member named by id still refuses join fields (`not_with_agent_id`) (`docs/api.md` §3.1,
  §6.2, §15.6, §15.9, not built).
