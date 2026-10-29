### Added

- web: **Agents that stop listening** in the account's notification settings (§18.4): a request
  once an hour, an item on the bell or nothing, and after how many minutes (10–1440).
- web: a project's **My settings** tab (`/<owner>/<slug>/my-settings`, §6.2) for every human member:
  one's default or a value for this project, with what applies now. The fixture hub answers
  `GET`/`PATCH …/me/settings` and checks `not_listening` as the hub does.
- web: a request the hub files itself is named as Maity's, without a "Meanwhile" line; the
  not-listening digest links to `/agents`, and so does the bell's `agents_not_listening` item.
- docs: §16.11 names the project view `my-settings`; §18.2 names the item target `agents`.
- hub: `my-settings` is a project view a slug may not take (§16.11).
