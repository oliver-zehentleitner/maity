### Changed

- docs: `context/performance.md` item 11 records that loading the
  single-page scripts on demand is parked, with the reason. `web/README.md`
  and `web/context/maintenance.md` say that the boot's notifications head
  drops a running window's 503 `maintenance` too and does not pass it to
  `M.onMaintenance`, as the code has done since #2036.
