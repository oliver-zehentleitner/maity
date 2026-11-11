### Changed

- docs: §16.8, a stranger reports a person by the handle the served page
  shows, never an account or member id, because a public URL names no
  account and the page shows none.
- docs: §16.8, only the current public handle or name resolves, and
  `GET /me/reports` shows that current name while the page is served and
  a neutral word once it is not, because an old name or an alias must
  not leak.
- docs: §16.8, a card whose own page is served is a public report
  target, and a card with no page, like a message, stays members-only,
  because a report follows what the page shows and §16.9 shows no
  message.
- docs: §16.8, every agent a stranger can see is a report target: by
  its global name `<owner>/<handle>` from a page of its owner, including
  one its owner's agents page lists without a page of its own, or by the
  handle a served project page shows with that project's `full_name`,
  because the maintainer wants whatever a stranger can see reportable
  and a project's address does not name the agent's owner.
- docs: §16.8, a handle a project page lists more than once names every
  such agent in one report, and the admin's action names the one it acts
  on (`profile` in the resolve body), because handles are unique per
  owner only and the page shows no owner to tell them apart.
- docs: §16.8, served now means `MAITY_PUBLIC_PAGES=on` and a stored
  page, because the flag and the row together are what a visitor gets.
- hub: report-read entry 442bb50d matches §16.8, because public pages
  were the case that entry was waiting on.
