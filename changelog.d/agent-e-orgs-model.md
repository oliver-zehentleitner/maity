### Added

- hub: organisations (§6.26), part 1: `POST`, `GET /orgs`, `GET`, `PATCH`, `DELETE /orgs/{org}`, the members and their roles (`GET /orgs/{org}/members`, `PATCH`, `DELETE …/members/{id}`) with `org_last_owner`, `org_role` and `org_limit` (`MAITY_MAX_ORGS_PER_HUMAN`, default 5); a human's and an organisation's handle share one namespace, kept by the database (migration `0087`). The account deletion refuses `org_last_owner` for the last owner of an organisation and ends the memberships; the export lists the organisations. Invitations, the organisation's projects, the rename and the public page follow (tsk-whe4wv1jpsae).

### Changed

- hub: the handle of a new account is checked against the organisations' handles too; `maity-hub owner create` refuses a handle an organisation has.
