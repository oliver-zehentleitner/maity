### Fixed

- cli: an error answer whose `code` is not a string (a proxy's `{"error": {"code": 409}}`, or
  `[]`, `{}`) no longer crashes `maity` commands with a TypeError (regression in 0.1.0a7), and
  one whose `error` is not an object (`{"error": "text"}`) no longer with an AttributeError.
  Such a code reads as no code, and such an `error` too unless a `Maity-Error` header names the
  code: the message, exit 1 and `maity-error <nonce>: -`, and the runner reports `join_failed`
  with detail `null` again, not a crash.
