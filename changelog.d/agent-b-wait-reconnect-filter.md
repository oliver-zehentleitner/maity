### Added

- cli: `maity wait --related` returns only events related to the agent (a
  message or request, a project state, policy or rules change, a mention, an
  event about it, addressed to it or its instance, or to a card's watchers or
  restricted-access list it is on) and
  reads past the rest, such as other members' `member_availability_changed`
  and `member_updated`; opt-in, not with `--keep-cursor`.

### Changed

- cli: `maity wait` retries a dropped connection, an answer cut short or
  that is no page of events, an HTTP 5xx or 429 silently
  until the hub has given no answer for 60 seconds, counted across waits;
  then one line names the UTC time of the first failed read and the time
  now, and another says when the hub answers again. When the minute passes
  during the read that answers, one combined line names both. Exit codes
  are unchanged.
