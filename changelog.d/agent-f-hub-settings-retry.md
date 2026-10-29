### Fixed

- hub: `PATCH /me/notification-settings` runs again after a deadlock, so three first changes at
  the same moment on MariaDB no longer answer 500 for one of them.
- hub: a `browser.kinds` entry that is not a boolean is refused as `browser.kinds.<kind>`, as the
  mail kinds are.
