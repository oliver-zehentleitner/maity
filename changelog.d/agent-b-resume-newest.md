### Fixed

- hub: the resume packet's `requests.answered_since_cursor` keeps the newest 100 answers, in the
  order they were answered, instead of the 100 requests asked first; a rejoin after a long absence
  showed old answers and dropped the latest (docs/api.md §5.2 now states the cap of 100 per list).
