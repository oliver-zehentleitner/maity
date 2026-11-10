### Fixed

- hub: the reason of an admin's reset of a second factor (`POST /admin/users/{id}/second-factor/reset`)
  is refused when it holds a control character other than a line break or a tab, which a NUL would
  have turned into a database error on PostgreSQL.
