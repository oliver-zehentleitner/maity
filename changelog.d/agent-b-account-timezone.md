### Added

- Account → Settings has a time zone. Every absolute time on the dashboard is shown in it, and in the browser's zone while none is set. `GET /me` carries it as `member.timezone`.

### Changed

- The notification settings' `timezone` is the account's time zone and reads `null` until it is set. `PATCH` takes `null` to unset it, and the mails use UTC while none is set.
- The mail settings no longer have a time zone field; they name the account's zone and link to Settings.
