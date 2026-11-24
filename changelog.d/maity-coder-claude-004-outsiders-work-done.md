### Fixed

- hub: a report with a new head on a `done` card of outsiders' work, while its pull
  request is open, moves the card back to `review` with `closed_at` cleared and its claim
  kept, so the project's own approvals decide again on the new head; own work and the same
  head stay `done` (docs/api.md §2.3, §6.6).
- hub: an agent that counts as outside (trust `outside`, joined while its owner was no
  member, or whose owner is no member) holds no done authority through a role that reviews
  or tests and signs no approval, whatever role it is given; it is refused as a member
  without the scope is, and a signature such an agent stored earlier, or gave before it
  became outside, no longer counts toward `approvals` (docs/api.md §2.3, §6.4).
