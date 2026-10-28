### Changed

- hub: the log line for a database connection error now carries the original exception's class and
  a category of its cause (`dns`, `timeout`, `refused`, `closed`, ...), so a burst of
  `database_unavailable` answers can be told apart. The driver's text is never logged. The answer to
  the client is unchanged.
