### Changed

- web: the end-to-end test starts one more hub, with the lowest read limit per credential
  (60 a minute), spends the reads of a new signed-in session for each load until the first
  refusal, takes it only with a Retry-After of at least 10 s, and checks the page that could not
  load: in English the hub's message under Details, in German the catalog's sentence for
  `rate_limited`, the hub's `read limit:` log line and an axe pass. An `extra` setting now
  overrides `start_hub`'s defaults instead of failing.

### Fixed

- docs: humans.md says what a page past the read limit shows: "Maity couldn't load this page"
  with the hub's message in English, the translated sentence in another language, and "Could
  not load" in a view when only the view's own read was refused.
