### Added

- hub: a human places a profile of their own that is not a member of the project yet by
  `{"agent": {"id"}}`, with the right to create its first join (`members:admin`, or trust
  `member` under `policy.member_agents`) on a runner of their own. The placement takes and
  stores the first join's fields under that join's checks and limits (`owner_only`,
  `member_join_limit`, `member_agents_max`, counting as the profile's open first join); its
  pickup is that first join, re-checked for `creator_lacks_authority` and
  `project_not_allowed` at the pickup and at the exchange against the policy as it is then
  (a member's placement ends once `member_agents` is `off`, or once the `reports_to` it stored
  is no longer the member or their own manager), and a profile that is a member
  by then gets a further instance within `max_instances` (`instance_quota` beyond it), only
  while the creator may add an instance to that membership.
  Removing or isolating an agent's membership also closes the project's placements of its
  profile that hold no credential yet; deleting a profile closes the placements that would
  admit it, and such a placement is never created for a profile being deleted.
  Migration `20261120205253_plc_agent_id` adds `placement.agent_id` (`docs/api.md` §3.1, §6.2,
  §15.6, §15.9).

### Fixed

- hub: a placement that creates a profile takes `subagents` and `subagents_language` as a join
  does, and its pickup's join carries them to the membership (`docs/api.md` §15.6).
