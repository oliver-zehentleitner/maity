### Changed

- cli: one helper each for the "every page" read, the `more:` line, a card's linked pull
  requests, JSON read from a file or stdin, project paths and the dict helpers, in place of
  copies in `cli.py` (tsk-sgaz43qazfzx). Behaviour stays the same, except: `jourfixe statement
  --file`, `jourfixe report --file` and `jourfixe answer --file` now say why a file is not JSON
  with the parser's full message (position included), and they also turn any other decoder
  `ValueError` (for example the integer conversion limit) into a usage error, where they used
  to catch only `JSONDecodeError`; a non-object file for `jourfixe answer` says "the body is
  one JSON object" before the keys are checked; and `hub.USER_AGENT` and `MESSAGE_TYPES` are
  gone. `--review-file` still turns any decoder `ValueError` into a usage error, as it already
  did.
