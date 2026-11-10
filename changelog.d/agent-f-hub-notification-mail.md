### Added

- hub: notification mail (`docs/api.md` §18.4, §18.5) — for each human with a verified
  address, a pass once a minute turns the unread `inbox`, `chat` and `mention` items into
  mail by the human's modes: `immediate` (items of one two-minute window in one mail, at
  most ten an hour, then the hour's digest), `hourly`, `daily` at `daily_at` in the human's
  time zone, outside quiet hours; one mail per pass, merged when the instance's
  `max_per_hour` is reached. Plain text, one subject per item or `N updates`, up to 50
  items grouped by project, the hub's own links only, text from others quoted and defanged,
  a message's text only where the human asked for it, `List-Unsubscribe` with RFC 8058
  one-click. A new sign-in is a mail of its own, a `security` mail. The open matters
  (`registration_pending`, `mail_disabled`) are never mailed. A human whose notifications
  did not move since the last pass is not derived again. Migration `0065`:
  `mail_item_sent` and `notification_mail_state`.
