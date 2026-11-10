### Added

- hub: the notification kind `invitation` (§18.1, §18.4). The consent request of an invitation
  by handle reaches the person as an `invitation` item with its own browser switch and mail mode,
  `immediate` by default; `daily` mails invitations with the daily digest and `off` keeps them
  on the platform only, whatever the inbox's mode. The counts stay as they were.
- web: the bell, the notifications page and its `kind` filter, and the browser notifications know
  the kind `invitation` (labelled "Invitations"), so an invitation is listed and shown like the
  other kinds.
