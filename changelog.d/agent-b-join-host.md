### Added

- hub: the optional join host (`docs/api.md` §1.1, §3.1–3.3) —
  `MAITY_JOIN_URL`, checked at startup; on that host `GET`/`POST /{token}` are
  the join page and the exchange (routed, never redirected), a dead
  token-shaped link answers a page saying the link no longer works, every
  other `GET` is a `302` to the public start page and every other method
  `not_found`, and no cookie or `Authorization` header is read; the host is
  matched on its hostname alone (any port, trailing dots ignored), and the log
  masks the first path segment there; joins take
  `via` (`join` by default when a join host is configured, `public` otherwise,
  `no_join_host` without one) and list it; `GET /auth/session` returns
  `join_url`; the join page's exchange and CLI line follow the host it was
  opened on, every later URL is the public one; the Helm chart's
  `ingress.joinHost`. The join page lives at `/join/{token}` and links are
  built there, `/j/{token}` stays as an alias (#104); `MAITY_CLI_INSTALL` is
  the install line on the page, in `/help` and in `signature_required` (one
  line, or the hub does not start), and
  the page says where the credential lives (`MAITY_STATE_DIR` outside a clone,
  #113).
