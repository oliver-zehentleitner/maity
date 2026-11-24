### Changed

- hub: an outsider's agent (trust `outside`) reads its role's memory but
  neither writes nor deletes it, as a guest does: `POST …/memory` with
  `store: role` and `DELETE …/memory/{id}` on a role entry answer
  `forbidden` with `details.reason: outside_trust`. Its own agent memory is
  unchanged.
