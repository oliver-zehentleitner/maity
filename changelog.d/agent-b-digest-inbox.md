### Added

- hub: the not-listening digest under `not_listening.mode: inbox` (the default): one personal
  request per owner, `<n> of your agent instances are not listening`, class `info` with `seen`,
  no asker, no project; rewritten in place while it is open, withdrawn when no instance is away
  any more and at the `PATCH` that leaves `inbox`; after `seen` only an episode that started
  later files a new one (§5.3). Migration 0108 lets such a request have neither project nor
  organisation

### Changed

- hub: a not-listening episode files no request of its own in any mode; the first digest hour
  withdraws the requests per episode that are still open (§5.3)
