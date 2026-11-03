### Added

- docs/api.md §6.5, §8.2: `holder_stalled` when an instance that holds cards declares a limit,
  loses its session to a revoked credential or instance, or stops listening, and `claim_expired`
  once per lease that runs out; both wake the member the agent reports to, name the cards and the
  reason, and release nothing.
- docs/api.md §5.3, §18.1, §18.4: the owner's hourly digest also lists ended sessions that still
  hold cards, under the same `not_listening.minutes`; the bell's `agents_not_listening` record
  gains `holding`.
