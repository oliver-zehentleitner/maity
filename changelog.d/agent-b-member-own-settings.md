### Added

- hub: `not_listening {mode, minutes}` in the notification settings
  (`GET`/`PATCH /me/notification-settings`, §18.4), default `inbox` after 60 minutes
- hub: a member's own settings in a project, `GET`/`PATCH
  /projects/{owner}/{slug}/me/settings` with the override `not_listening.minutes` and
  the `effective` value (§6.2); humans only, migration 0091
