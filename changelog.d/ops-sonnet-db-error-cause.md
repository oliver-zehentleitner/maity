### Changed

- hub: the log line for a database connection error now carries the original exception's type and
  its text with URLs and `password=` pairs masked, so a burst of `database_unavailable` answers can
  be told apart (DNS, timeout, refused). The answer to the client is unchanged.
