### Fixed

- cli: under a runner placement, `maity say --type review_result` sends nothing and exits 1
  when maity's git refuses the runner's clone (for example a configuration key that runs
  code). Before, the review went out with "cites and text not checked". A commit missing
  from the clone is still sent with that note.
