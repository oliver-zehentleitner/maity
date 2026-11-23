### Fixed

- hub: the tests of the `merge.public` backfill run on the test clock, so they no longer
  fail once the calendar date is 30 days past the fixed test time; a ticker merge's
  `merged_at` in the tests is taken from that clock too.
