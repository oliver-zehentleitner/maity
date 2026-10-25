### Added

- hub: notification mail (`docs/api.md` §18.4, §18.5) — per kind
  `immediate` (after a two-minute window, at most ten mails an hour, the
  rest with the hour's digest), `hourly`, `daily` at `daily_at` in the
  human's time zone, or `off`; nothing but security mail in quiet hours;
  each item checked against what the human may read when the mail is
  built, mailed once, and only from the time the address was verified.
  Subjects and digests as §18.5 says (50 items, "and N more"), text the
  hub did not write quoted and defanged, the message text only where
  `content` asks for it, `List-Unsubscribe` and one stop link per kind.
- hub: a new sign-in mails its own security alert (time, method,
  browser, system, address; never a session id), immediate or off.
