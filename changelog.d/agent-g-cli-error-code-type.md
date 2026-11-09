### Fixed

- cli: an error answer whose `code` is not a string (a proxy's `{"error": {"code": 409}}`) no
  longer crashes every `maity` command with a TypeError (regression in 0.1.0a7). It reads as no
  code: the message, exit 1 and `maity-error <nonce>: -`. The runner reports `join_failed` with
  detail `null` again, not a crash.
