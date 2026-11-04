### Changed

- hub: a session a runner supervises is left out of "not listening" (§5.3)
  only while an active placement names its credential. A stopped local
  mode (§15.13), or a supervised session whose placement was closed, now
  starts an episode and `member_not_listening` like any other session;
  before, every supervised session was left out.
