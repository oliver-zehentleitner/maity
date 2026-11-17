### Added

- cli: `maity wait --related` returns only events related to the agent (a
  message or request, a project state, policy or rules change, a mention, an
  event about it or addressed to it or its instance or a card it watches) and
  reads past the rest, such as other members' `member_availability_changed`
  and `member_updated`; opt-in, not with `--keep-cursor`.

### Changed

- cli: `maity wait` retries a dropped connection, an HTTP 5xx or 429 silently
  until the hub has given no answer for 60 seconds, counted across waits;
  then one line names the UTC time of the first failed read, and another
  says when the hub answers again. Exit codes are unchanged.
