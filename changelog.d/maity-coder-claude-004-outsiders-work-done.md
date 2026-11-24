### Fixed

- hub: a report with a new head on a `done` card of outsiders' work, while its pull
  request is open, moves the card back to `review` with `closed_at` cleared and its claim
  kept, so the project's own approvals decide again on the new head; a card without a
  holder goes to `open` instead, where the normal claim applies; own work and the same
  head stay `done` (docs/api.md §2.3, §6.6).
- hub: an agent that counts as outside under the own-approvals rule (docs/api.md §2.3,
  "Own approvals") holds no done authority through a role that reviews
  or tests and signs no approval, whatever role it is given; it is refused as a member
  without the scope is, and a signature such an agent stored earlier, or gave before it
  became outside, no longer counts toward `approvals` (docs/api.md §2.3, §6.4).
