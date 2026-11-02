### Added

- web: `make check` compares what the fixture hub answers to 14 requests with the hub's recorded
  answers (`web/tools/hub-shapes.json`, re-recorded by `make -C web shapes`); a key or type the
  hub does not send is a finding unless the shrinking baseline lists it.

### Fixed

- web: in fixture mode the conversation lists no longer carry `created_by` and `closed_reason`,
  which the hub sends only in a group chat's own view.
