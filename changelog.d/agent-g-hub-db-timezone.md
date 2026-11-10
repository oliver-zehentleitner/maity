### Fixed

- Hub on PostgreSQL: lease ends during a limit and a credential's first `resumed_at` no longer depend on the database server's time zone (they were shifted by its offset from UTC, e.g. one hour in Vienna). Every hub connection now sets `TimeZone=UTC`, and times inside SQL expressions are bound with their column's type.
