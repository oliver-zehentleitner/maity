### Security

- hub: a credential id the hub could not have issued (wrong prefix, length or characters,
  non-ASCII) is refused with `401 unauthenticated`, the answer of an unknown id, before any
  database lookup: on a signed request's `Maity-HMAC` header, a bearer value and the large-body
  precheck alike, for agent and runner credentials.
