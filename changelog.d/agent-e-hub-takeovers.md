### Added

- hub: takeovers within one owner's agents (`docs/api.md` §6.19) — `POST
  …/tasks/{id}/takeover` opens one with a window (`takeover_window_minutes`, a
  project policy field), the holding instance accepts or objects, the requester
  withdraws, the admin team overrides; the window's end transfers the card, as
  does an expired lease at once and a human admin's takeover; a card a human
  holds is never taken over; an agent's `assign`, `release` or `PATCH
  assigned_to` of a card another agent holds is `takeover_required` while the
  lease runs and `takeover_open` while a takeover is open, and after the lease
  ran out it is recorded as a `lease_expired` takeover; `GET …/takeovers`;
  a disputed takeover is escalated by either party, or by itself after a second
  window, as a `decision` request to the admin team (`transfer` / `keep`,
  `takeover_id` on the request), whose answer closes it; a proposal kind can now
  narrow who answers (`party_to_takeover`, `admin_team_only`), require a reply,
  and learn the reply chosen
