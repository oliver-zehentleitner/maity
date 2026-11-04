### Added

- hub: `holder_stalled` when an agent instance that holds open cards stops: a limit starts, its
  session is revoked (not by a replacement or the member's removal) or a not-listening episode
  starts; `claim_expired` once per holder and minute for the leases of open cards that ran out,
  each lease once (§6.5). Both go to the member the agent reports to (else the admins), the owner
  and the holding instance, and wake only the agent it reports to. Nothing is released.
- hub: new column `card.lease_expiry_reported`; the migration marks the leases already expired
  as reported, so they are not reported after the deploy.
