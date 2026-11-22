### Changed

- hub: a join that no longer works still answers the same bare `not_found`,
  and the hub's log now says at info which check refused it (no such token,
  revoked, used, burned, expired, no attempt slot with the join's state, a
  concurrent exchange, the creator or the profile's allowed projects, a
  removed member, a pickup that no longer holds). Only the join's row id is
  logged, never its token or code.
