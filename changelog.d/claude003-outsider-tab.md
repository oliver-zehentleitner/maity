### Added

- web: a public project one is no member of is a tab with a dashed outline
  once its page is opened, kept for the browser session (sessionStorage)
  until it is closed from the tabs menu, where it is listed as not a
  member; inside it still shows the public page, until the hub's outsider
  read lets it open the member views.
- web: starred projects (`/me` `starred`) are dashed tabs among one's
  tabs, opened after `start_tabs` in a fresh browser and appended when a
  star is added elsewhere; their filled star takes the star off with
  `PATCH /me {"starred": [...]}`, the tab staying for the session, and a
  refusal is said with its reason. Closing a starred tab keeps the star.
- web: the fixture hub takes `starred` on `PATCH /me` with hub/stars.py's
  refusals (`required`, `duplicate`, `member`, `not_public`, `too_many`).
