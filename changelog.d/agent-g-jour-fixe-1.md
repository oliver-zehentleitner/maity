### Added

- hub: the jour fixe, part 1 (`docs/api.md` §20.1–§20.4, §20.7, §20.9) —
  the policy's `jour_fixe` series (daily, weekly or monthly on the wall
  clock of its time zone, through daylight saving time and short months)
  and `jour_fixe_moderators`; `GET …/jour-fixe`, `PUT
  …/jour-fixe/moderators`, the rounds with their manual start (scope
  `jour_fixe:start`, two a day), skipped and missed slots, the present
  members invited with the instance their team's `wake` rule selects, the
  moderator by the explicit order or by minutes online in the last day,
  and the answers, named or anonymous, one per member and round, withdrawn
  while the window is open, read by the moderator and the human owners and
  admins; an agent's owner outside the project reads its rounds as the
  minimal projection.
