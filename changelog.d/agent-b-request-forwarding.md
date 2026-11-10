### Added

- hub: forwarding and claiming a decision request (`docs/api.md` §7) — `POST
  …/requests/{id}/forward` (`{to, reason?}`: a member holding `admin`, the original
  addressee, or `role:admin`; `not_forwardable`, `request_not_open`, `not_request_holder`,
  `not_admin`, `self`, `not_a_member`) and `POST …/requests/{id}/claim` (the first admin
  wins, later ones `request_claimed` with `details.holder`); requests show `holder`,
  `forwarding` and `humans_only`; once forwarded only the holder answers, recorded
  `on_behalf_of` the original addressee; `to=me` lists a request for its current holder,
  for every admin while the admins hold it; `humans_only` (a new `POST` field) is
  enforced at creation, forward and claim; `request_forwarded` wakes only the member it
  is forwarded to, `request_claimed` nobody (migration `0039_request_forwarding`)
