### Security

- hub: a replayed `Idempotency-Key` passes the same read access check as a fresh request
  (§1.5). Before it answers with the resource as it is now, the hub checks that the caller
  may still read it, the way its GET does: an active membership with `project:read` and the
  resource's own read rule, or for resources outside a project their owner or readers.
  Otherwise the replay answers `not_found`. Every resource type registers its check next to
  its loader (`idempotency.register`), and a test names every registered type.
