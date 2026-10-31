### Changed

- cli: `maity join` and `maity resume` print a compact text by default: the last 10 answers and
  the last 10 events addressed to this member or instance, the rest counted in one `Not shown`
  line, bodies cut at 5 lines or 200 characters. A realistic rejoin stays under 8 KB. The text
  ends with one `Next:` action that includes starting `maity wait` in the background.

### Added

- cli: `maity resume --full` prints the last resume's packet in full from the state directory
  (`last-resume.json`, 0600), without calling the hub.
