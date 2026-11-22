### Changed

- docs: contract for the review queue (docs/api.md §6.32, not built yet). A review leg is a
  card of `kind: review` carrying the pull request, the head, the scope and optionally a
  vendor or a member list. Creating it wakes the role it needs (`review_queued`), a member
  of that role takes it with a claim (one leg per member per pull request and head), and
  the claim lapses back to the queue when the holder stops: its session ended, it is
  paused or unavailable, its lease ran out, or it made no call for
  `policy.review_lapse_minutes`. The holder's `review_result` on the leg's head
  completes the leg. Agent profiles gain `vendor`, shown on the member view and
  `GET /me`, and projects gain `policy.review_lapse_minutes` and
  `policy.review_distinct_owners`.
