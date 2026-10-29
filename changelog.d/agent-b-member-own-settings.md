### Added

- hub: `not_listening {mode, minutes}` in the notification settings
  (`GET`/`PATCH /me/notification-settings`, §18.4), default `inbox` after 60 minutes
- hub: a member's own settings in a project, `GET`/`PATCH
  /projects/{owner}/{slug}/me/settings` with the override `not_listening.minutes` and
  the `effective` value (§6.2); humans only, migration 0091
- hub: the data export (§2) carries `not_listening` with the notification settings
  and each membership's `own_settings`

### Fixed

- hub: the route words `me` and `repository` are in the reserved floor that `migrate`
  checks existing slugs against (§6.25, §16.11); a test keeps every route word of the
  hub in it
