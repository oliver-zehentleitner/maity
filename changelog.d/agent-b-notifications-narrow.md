### Changed

- hub: notifications are only what a human has to react to (`docs/api.md` §18.1, contract
  #409). The kinds are `inbox`, `chat`, `mention` and `security`. Cards, watches, the ticker
  and placements no longer make items, and items carry no `reason`. The derive and the held
  long-poll's stamp read only messages, `mentioned` and the request events, `request_forwarded`
  now included. `counts` and `by_project` carry the four kinds only. A removed kind in the
  `kind` filter is `invalid` with `removed_kind`, any other unknown kind `unknown`.
  A waiting registration is the instance admin's `inbox` item (`registration_pending`): it
  counts and stays listed until it is decided, and is never mailed. `mail_disabled` is an
  `inbox` item.
  A request is one `inbox` item, for whoever holds it now: an earlier holder, or the other
  admins once one claimed it, keep none. A new event index `(project_id, kind, seq)`
  (migration 0054) serves the long-poll's change check.
