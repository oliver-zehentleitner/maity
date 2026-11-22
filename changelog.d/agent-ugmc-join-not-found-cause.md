### Changed

- hub: a join that no longer works still answers the same bare `not_found`,
  and the hub's log now says at info which check refused it (no such token,
  revoked, used, burned, expired, no attempt slot, a concurrent exchange, the
  creator or the profile's allowed projects, a removed member, a pickup that
  no longer holds or whose new profile cannot be made, a deleted profile).
  At debug it also logs the join's state when the attempt slot is refused;
  normal serving makes no extra read for it. Only the join's row id is
  logged, never its token or code. The shared checks log the same line where
  they refuse outside the exchange too: the join page for a token that no
  longer works, and a deleted profile at join and placement creation.
