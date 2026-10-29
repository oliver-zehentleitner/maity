### Added

- docs/api.md §6.26: organisations as a second kind of namespace owner (`POST /orgs`, `/orgs/{org}`,
  `/orgs/{org}/members…`), sharing the namespace of human handles; roles `owner`, `admin`, `member`,
  members added only by a consent request; every organisation owner holds trust `owner` in its
  projects; `POST /projects` with `owner`, transfers into and out of an organisation; the project's
  `owner` gains `kind`, `GET /me` gains `orgs`; the instance limit `max_orgs_per_human` (default 5,
  `409 org_limit`), `409 org_last_owner`; organisation pages under §16.9; forge reads of an
  organisation's project with the grants of the confirming owner (`repository.confirmed_by`,
  §11.4); personal requests with `org` (§7, §18.1); `suspend` of an organisation (§16.8) and
  `GET /admin/orgs` (§16.10); context/projects.md records the decision
