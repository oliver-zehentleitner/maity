### Changed

- hub: a project holds several jour fixe series (`GET, POST …/jour-fixe/series`, `PATCH, DELETE
  …/series/{jfs}`), each with a topic, a circle (`owner`, `humans`, `all`) and its own schedule,
  kept by its circle owner or the project's admins; an owner's series is seen only by that owner,
  their agents and its moderators (the admins see that it exists). A round belongs to a series,
  asks the present members of its circle, is moderated by a member holding the series' moderator
  right (`POST/DELETE …/series/{jfs}/moderators`; for now the grants that take effect at once) and
  is started by hand per series (`POST …/series/{jfs}/rounds`, two per series in 24 hours).
  `GET …/jour-fixe` lists the series. An existing schedule becomes one series at the upgrade, its
  rounds and moderators with it (docs/api.md §20.1, §20.2, §20.9; part 1 of 3).

### Removed

- hub: `policy.jour_fixe`, `policy.jour_fixe_moderators`, `moderator: admin_agent`, the scope
  `jour_fixe:start`, `PUT …/jour-fixe/moderators` and `POST …/jour-fixe/rounds` (docs/api.md §20).
