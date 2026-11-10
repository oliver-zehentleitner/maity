### Added

- hub: organisations (§6.26), part 3a: projects of an organisation. `POST /projects` takes `owner`, the handle of an organisation the caller may create in (an owner or admin, a member while `members_create_projects`); the hub keeps every owner of the organisation a member with trust `owner` of every project it owns, archived ones included (`member_joined`, `member_updated`), and ends or returns those memberships when someone stops being an owner; the human member view carries `org_owner`; no call demotes or removes such an owner (`namespace_owner`); an organisation with a project that is not archived cannot be deleted (migration `0089`, tsk-whe4wv1jpsae).

### Changed

- hub: `project.owner_id` and `project_alias.owner_id` are no longer foreign keys: `owner_human_id` and `owner_org_id` are, exactly one set.
