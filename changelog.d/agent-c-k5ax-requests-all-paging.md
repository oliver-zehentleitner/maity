### Changed

- hub: `GET /requests` (the inbox across projects) pages in the database. For each project it
  reads the keys of the requests the caller sees after the cursor, the page plus one, as the
  project's list does, and the personal requests the same way. It merges them by key and reads
  only the page's rows in full, and decides those rows again by the same rules, so a request
  that changed after its key was read is shown only if the caller still lists it. Before, every page read every matching request of every project
  in full. The order, the items and the cursors are unchanged, and a cursor handed out before
  keeps working. As on the project's list, a page may then hold fewer than `limit` items,
  rarely none with a `next_cursor`, and its cursor is built from the rows it keeps.
