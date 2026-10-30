### Added

- web: **Agents that stop listening** in the account's notification settings (§18.4): a request
  once an hour, an item on the bell or nothing, and after how many minutes (10–1440).
- web: one's own settings for a project, for every human member (§6.2; now the **Mine** tab of the
  project's Settings at `/<owner>/<slug>/settings/mine`, §16.11): one's default or a value for this
  project, with what applies now. The fixture hub answers
  `GET`/`PATCH …/me/settings` and checks `not_listening` as the hub does.
- web: a request the hub files itself is named as Maity's, without a "Meanwhile" line; the
  not-listening digest links to `/agents`, and so does the bell's `agents_not_listening` item.
- docs: §18.2 names the item target `agents`.
- docs: `agents_not_listening` is an open matter of §18.2–§18.3, the fourth beside `registration_pending`, `report_open` and `mail_disabled`: never marked read by a
  caller, read once no instance is away any more; the bell does not mark it read when opened.
