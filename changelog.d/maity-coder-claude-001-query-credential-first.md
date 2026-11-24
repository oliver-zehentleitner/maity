### Security

- hub: a credential in the query string is refused with `credential_in_payload`, and a real
  one revoked, on every request, also where the hub answered first before: an unknown API
  path, a maintenance window, an operator's route limit, a body declared over its cap and
  the forge webhook. The query is checked before any other answer, and the body of such a
  request is not read.
