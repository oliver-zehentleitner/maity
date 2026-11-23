### Fixed

- hub: the entry on the `merge.public` backfill tests, corrected: they failed once the calendar
  date was 29 days past the fixed test time, not 30 (their ticker items are dated a day before
  it and leave the 30-day window 30 days after their own day).
