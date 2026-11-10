### Fixed

- hub: the test of a multi-ping `Retry-After` freezes the limiter's clock; across a
  second boundary it saw 599 instead of 600 and failed now and then on PostgreSQL
