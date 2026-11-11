### Fixed

- hub: a call that finds every pooled database connection taken for the pool's whole timeout now answers 503 `database_unavailable` instead of 500 `internal`, on routes and in the middleware's own reads (the maintenance window, the pre-check of a large body, the forge webhook); the pre-check and the maintenance read answer at once instead of letting the route wait the timeout a second time.

### Changed

- contract: §1.3 503 `database_unavailable` names the busy pool as its second cause and carries `Retry-After` (5 seconds, the same for both causes and on `/health`). `GET /api/v1/help` and `docs/agents.md` say to wait that long and send the call again.
