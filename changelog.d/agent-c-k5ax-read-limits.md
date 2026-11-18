### Added

- hub: a signed-in credential's reads of the API have a limit per minute
  (tsk-ybc2ma72dzvq, item 7): the `GET` and `HEAD` calls under `/api/v1/` of
  an agent's credential, a runner's and a dashboard session, a bridge's
  calls with `Maity-For` against the bridge's own. Past it a read is
  `429 rate_limited` with `Retry-After`, the seconds until one more fits,
  and changes nothing (no last use, presence or lease). Writes, and calls
  without a credential, are not counted; the events long-poll and
  `GET /bootstrap` count once per call. Operators: the new setting
  `max_reads_per_minute`, `MAITY_MAX_READS_PER_MINUTE` or the instance
  admin's Limits, defaults to 1000, about 3.6 times the highest sum of all
  clients' reads per minute measured on the hosted instance; set it from 60
  to 100000, or `unlimited` to switch it off. It counts in each process (with
  several replicas each counts its own share); an admin's change applies at
  once in the process that takes it and within 30 seconds in the others.
  Every refusal writes one INFO line to `maity_hub.read_limits` with the
  route and a 12-character tag of the credential (an HMAC under the instance
  key, or a key of the process without one), never the credential, its id
  or the session; count those lines before lowering the value. A project's
  own lower value (`policy.max_reads_per_minute`) follows later.
- hub: a read is counted by the path the router matches, its percent-escapes
  decoded (docs/api.md §1.7).

### Changed

- hub: a dashboard session is checked before its presence is written: an
  ended, expired or deleted account's session sends no presence write at
  all, and a call within the minute after the last one sends none either.
