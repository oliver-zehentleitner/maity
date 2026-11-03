### Added

- hub: `holder_stalled` when an agent instance that holds cards stops: a limit starts, its
  session is revoked (not by a replacement) or a not-listening episode starts; `claim_expired`
  once per holder and minute for the leases that ran out, each lease once (§6.5). Both go to the
  member the agent reports to, the admins, the owner and the holding instance, and wake only the
  first. Nothing is released.
