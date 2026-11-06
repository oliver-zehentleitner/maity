### Changed

- docs: when the probe sees merges it missed while they happened, §17.4
  of `docs/api.md` delivers the usual ticker item and wake only for a
  merge whose `merged_at` is at most 1 hour before that delivery, on the
  hub's clock. An older missed merge is discarded: no ticker item, no
  wake, no notification, no card link and no count change. The
  merge-scan cursor (`scanned_until`, and the round's progress) still
  advances. The first run after the ticker is enabled is unchanged: it
  starts at switch-on and announces nothing older.
