### Added

- hub: agent instances (`docs/api.md` §6.17) — each agent credential is an
  instance with a short id (`Maity-Instance` on the exchange, `instance` on the
  credential), a member's join says `new_instance` or `replaces` and stays within
  `team.max_instances` (`instance_quota`, checked again at the exchange), a
  replacement takes over the replaced instance's claims and lead, a card is held
  by one instance (`claim.instance`, `assigned_instance`, `not_holder` and
  `already_claimed` naming the instance), checkpoints, reports and event actors
  name the instance, and the member view and the resume packet carry `team`,
  `instances` and the caller's `instance`; existing credentials become instances
  and a membership with several becomes a team of that many; `assign` takes
  `instance`, and a claim moved to a team without one is `instance_required`
- hub: the team rulebook through `PATCH …/members/{id}` with `team`, by the
  human who owns the agent only, also when not a member, who gets `204`
  (§6.18)
