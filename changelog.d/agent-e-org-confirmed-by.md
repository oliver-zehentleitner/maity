### Added

- hub: `repository.confirmed_by` (§11.4): `{id, handle}` of the human whose forge grants the confirmation put to use, `null` while it is not confirmed; any owner of an organisation confirms the repository of one of its projects with their own grants (`POST …/repository/confirm`), a later confirmation by another owner replaces them, and the confirmation ends when that owner stops being one (demoted, removed, leaving, their account deleted) (migration `0099`, tsk-whe4wv1jpsae).
