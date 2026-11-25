### Changed

- cli: one helper each for the "every page" read, the `more:` line, a card's linked pull
  requests, JSON read from a file or stdin, project paths and the dict helpers, in place of
  copies in `cli.py` (tsk-sgaz43qazfzx). Behaviour stays the same; `--review-file` and
  `jourfixe answer --file` now say why a file is not JSON with the parser's full message, and
  `hub.USER_AGENT` and `MESSAGE_TYPES` are gone.
