### Changed

- hub: the probe's merge scan discards a missed merge whose `merged_at`
  is more than one hour before delivery, and still advances the scan
  cursor. A merge exactly one hour old is announced. The forge is not
  read for a merge already past the hour, and a merge that passes that
  hour while its files are read is not written either.
