### Added

- hub: `GET /public/explore` lists the projects `/explore` shows, as
  `{name, full_name}`, the same answer for everyone (`public, max-age=60`,
  an `ETag`), for the dashboard's Explore tab.

### Changed

- hub: `/explore` answers a signed-in human with the app shell, where the
  dashboard draws Explore; a visitor, and anyone with `?as=public`, keeps the
  page as before.
