### Fixed

- hub: a chat or project message read again carries `deleted_at` on a
  file deleted since, so the dashboard no longer offers it again after a
  reload.
- hub: the overview's latest reports name the reporter's `instance`, and
  a group chat in the conversation list carries its `created_at`.
