### Security

- hub: on MariaDB a public page taken off can no longer be written back by a
  render that read its target before the takedown. A render, a takedown and the
  cleanup of the stored pages lock the target's row in the new
  `public_page_lock` table until their transaction ends, as PostgreSQL holds an
  advisory lock. Before, the lock was a no-op off PostgreSQL, while one process
  still renders from several threads. One migration; the table stays empty on
  PostgreSQL and SQLite.
