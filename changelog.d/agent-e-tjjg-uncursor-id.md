### Fixed

- hub: a page cursor ordered by time (the card list's `order=updated`, conversations,
  takeovers, contacts, runner enrollments, reports, the admin's organisations and maintenance
  changes, and the other lists that use it) whose id holds a NUL or does not encode as UTF-8
  (a lone surrogate) is refused as `400 invalid`, instead of failing at the database with a
  500.
