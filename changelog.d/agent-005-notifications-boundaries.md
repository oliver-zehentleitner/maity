### Changed

- hub: `GET /me/notifications` reads every project's position in one statement
  instead of one per membership; `open_requests` moved from `routes/me.py` to
  `inbox.py`, so the notifications no longer import a route module.
