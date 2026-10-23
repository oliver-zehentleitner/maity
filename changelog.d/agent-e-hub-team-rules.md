### Added

- hub: the team's rules at work (`docs/api.md` §6.18, §8.2) — `assign` sets
  `assigned_instance` on every path that assigns a card to a team (none under
  `free`), round robin rotates in order of creation, skipping revoked and paused
  instances and preferring online ones, the lead instance hands out its team's
  cards nobody holds, a claim by another instance is
  `instance_assigned`, one instance does not review another's work unless
  `review_within_team` (`same_team_review`), the holder and an assigned
  instance are named by `instance:` audience tokens that wake only that
  instance, a team's `lead` or `next_free` wake rule is recorded on the event
  as `wakes`, and a message may go to an instance address
- hub: an instance's own pause (§5.3) — `PATCH /me` pauses the calling instance,
  `PATCH …/members/{id}` takes `instance`, a human's pause of one instance
  refuses it new work while its siblings carry on; the instance view shows its
  pause and, to the owner, a workspace shared with a sibling, and a member's
  presence is the best of its instances'
