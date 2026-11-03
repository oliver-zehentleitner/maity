### Added

- docs/api.md §6.5, §8.2: `holder_stalled` when a limit starts for an agent that holds cards, when
  a holder loses its session to a revocation that is not a replacement, or when it stops listening;
  and `claim_expired`, one per instance and worker pass, naming the claims whose leases ran out.
  Both name the cards and the reason (a running limit first), wake the member the agent reports to
  when it is an agent, and release nothing.
- docs/api.md §5.3, §6.2, §18.1, §18.4: the owner's hourly digest also lists stalled holders,
  instances that hold cards and have made no call for `not_listening.minutes`, a crashed harness
  included; they count for filing, rewriting, withdrawal and `seen` like episodes; the bell's
  `agents_not_listening` record gains `holding`.
