### Changed

- cli: `maity wait` now prints every pending event, up to 50, as one JSON array by default.
  Before, it printed the first event alone as an object; `--one` keeps that output. `--batch` is
  still accepted and is now the default. **Scripts that parse the output as one object need
  `--one`.**

### Added

- cli: `maity wait --kind KIND` (repeatable) returns only events of those kinds. It reads past
  and acknowledges the others and keeps waiting, so a loop that waits for messages no longer
  makes one request per other event. It is refused with `--keep-cursor`.

### Fixed

- cli: `maity wait` prints and flushes the events before it saves the cursor, so a wait stopped
  in between has not acknowledged events it did not hand over.
