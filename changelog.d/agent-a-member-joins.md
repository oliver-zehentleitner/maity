### Added

- docs/api.md §3.1, §6.1: bringing your own agent — while `policy.member_agents` is `on`, a human
  with trust `member` creates joins for agents of their own (trust `member` or `guest`, roles
  coder/reviewer/tester/designer, reporting to them, no areas), at most `member_agents_max` (default
  3) per human; they list and revoke only their own joins.
