### Changed

- docs/api.md §20: a project holds several jour fixe series (`…/jour-fixe/series`), each with a
  `topic`, a `circle` (`owner` — one owner with their agents, `humans`, `all`) and its own
  schedule, kept by its circle owner or the project's admins. Moderating is a right per series,
  granted by a human who could set the member's `reports_to` and always consented to by the agent's
  owner (`…/series/{jfs}/moderators`); with nobody holding it present the round is skipped and the
  keepers are told. An owner's series stays with that owner: its round, answers and decisions.
  `policy.jour_fixe`, `policy.jour_fixe_moderators`, `moderator: admin_agent`, the scope
  `jour_fixe:start` and `PUT …/jour-fixe/moderators` are removed; an existing schedule becomes one
  series at the upgrade.
