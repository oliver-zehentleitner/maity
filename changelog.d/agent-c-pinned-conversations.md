### Added

- hub: a human pins conversations (§9.3 "Pinned"): `PUT` and `DELETE …/conversations/{id}/pin`,
  at most 20 across projects; every item of `GET …/conversations` and `GET /me/conversations`
  carries `pinned`, and both lists come in four bands, pinned with unread messages first, a quiet
  pinned chat below every chat with something new. A chat left or no longer readable keeps no pin.
