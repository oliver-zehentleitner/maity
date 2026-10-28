### Added

- hub: a human with trust `member` brings agents of their own (§3.1 "Bringing your own
  agent", §6.1): while `policy.member_agents` is `on` (the default) they create joins
  within the limits — trust `member` or `guest`, role `coder`, `reviewer`, `tester` or
  `designer`, reporting to them, no areas or capabilities, at most
  `policy.member_agents_max` agents (default 3, 0–20) counted under the project lock —
  and list and revoke only their own joins. The exchange checks the creator, the limits
  and the count again under the same lock. Both policy fields are a human's
  `project:admin` to set. Migration 0066.
