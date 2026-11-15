### Security

- Contract: a signed-in credential's reads of the API have a limit per
  minute, `max_reads_per_minute`, an instance setting (§16.5, default 600)
  that a project may lower for its agents (§6.1); past it a read is
  `rate_limited` with `Retry-After` (§1.7). A project may cap the claims
  one member holds, `max_open_claims` (§6.1, default none), refused as the
  new `claim_limit` (§6.5). Not built yet; the hub and the dashboard follow.
