### Fixed

- hub: account records, the record of which notification items were mailed, the mail delivery
  counts and stored notification positions are deleted by an hourly sweep of the mail worker,
  so "kept 90 days" (records) and "kept at least 30 days after its last use" (positions) now
  hold in the database, not only when read; sign-in records with their IP, browser and system
  no longer stay for good. An inbox record whose matter is still open (a waiting registration,
  a disabled address, agents away) is kept until it closes. The mailer reads only the sent
  marks of the last 91 days (tsk-3ar6h2s0kff5).

### Removed

- hub: the outbox sweep no longer runs the one-off update that emptied rows which left the
  queue before October's change; every way out of the queue empties the row itself
  (tsk-3ar6h2s0kff5).
