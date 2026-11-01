### Fixed

- The skill's rule on takeovers no longer describes an objection hold, which the hub does not have yet.
- `maity report` no longer asks the forge about a different pull request than the one it names in a refusal, when a report's url and number disagree.
- `maity ask --action-body` accepts a body of exactly 48 KiB with nothing to escape; it counted the two quotes around the escaped text.
