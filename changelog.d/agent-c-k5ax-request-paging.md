### Changed

- hub: `GET /projects/{owner}/{slug}/requests` pages in the database. It reads the keys of the
  requests the caller sees after the cursor, the page plus one, and only the page's rows in full.
  Before, every page read every matching request in full and sorted it in Python. Held, covered,
  jour fixe and (for a proxy) proposal requests are still decided by the listing's Python rule,
  reading only the columns it needs. The order, the items and the cursors are unchanged, and a
  cursor handed out before keeps working. A request that changes while a page is read is
  decided again on its full read: the page may then hold fewer than `limit` items, rarely
  none with a `next_cursor`, and its cursor is built from the rows it keeps.

### Fixed

- hub: a request-list cursor whose key has the wrong shape (a value of the wrong type, the
  wrong length, a rank outside 0 to 3, a time without a zone, an id that cannot be bound) is
  answered 400 `invalid` with `details.fields.cursor: "invalid"`, on the project's list
  (`GET /projects/{owner}/{slug}/requests`) and on the list across projects (`GET /requests`).
  Before, most such keys failed as a 500.
