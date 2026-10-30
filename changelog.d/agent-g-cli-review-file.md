### Added

- cli: `maity say --type review_result --review-file <path>` (`-` for standard
  input) sends the review object of `docs/api.md` §8.4 (`subject`, `head`,
  `verdict`, `cites`) as given; it is required with `review_result` and refused
  with any other type, and the message and the review cannot both come from
  standard input. The hub's indexed error paths (`review.cites.2.line`) are
  shown as they are.
