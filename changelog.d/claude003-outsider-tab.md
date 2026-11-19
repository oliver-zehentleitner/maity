### Added

- web: a public project one is no member of is a tab with a dashed outline
  once it is opened, kept for the browser session (sessionStorage) until it
  is closed from the tabs menu, where it is listed as not a member. The tab
  opens the project's member views, Overview, Board, Team and Why, read
  from the member routes the hub opens to an outsider (#2001; Why's
  routes pending a contract addition there), with the controls an
  outsider has no right to left out; every other view of the project is
  "not found", and the stored public page is never shown inside the tab.
  Signed out, a visitor still gets the public page.
- web: this session's dashed tab carries an empty star that stars it with
  `PATCH /me {"starred": [...]}`, the project's id last.
- web: starred projects (`/me` `starred`) are dashed tabs among one's
  tabs, opened after `start_tabs` in a fresh browser and appended when a
  star is added elsewhere; their filled star takes the star off with
  `PATCH /me {"starred": [...]}`, the tab staying for the session, and a
  refusal is said with its reason. Closing a starred tab keeps the star.
- web: the fixture hub takes `starred` on `PATCH /me` with hub/stars.py's
  refusals (`required`, `duplicate`, `member`, `not_public`, `too_many`),
  and answers a public project's member routes to an outsider as #2001
  does (`stranger/tool`), Why's two with the member shapes until #2001's
  contract addition names them.
