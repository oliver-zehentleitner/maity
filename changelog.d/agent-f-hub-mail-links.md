### Added

- hub: the unsubscribe link of a mail (`docs/api.md` §18.6) — `GET` and `POST
  /mail/unsubscribe/{token}` on the public host, no cookie, no session: the `GET` shows a
  page and changes nothing (mail scanners open links), the `POST` (the button, or the
  RFC 8058 one-click request) sets that kind's `mode` to `off`. A token is signed with
  `MAITY_MAIL_SIGNING_KEY` and the hub stores none; it works until the address changes
  (the `epoch` moves). A link that does not work, for any reason, is one page with
  `not_found`. The request log masks the token of `/mail/*`.
