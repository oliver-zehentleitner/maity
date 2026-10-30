### Changed

- Hub: the handover (docs/api.md §5.2) is read only up to the first packet's `events.after`
  (`events.read(until=)`) instead of looking past it page by page, an instance made before the
  handover's cursors existed falls back to its creation time, and the first packet carries the
  handover whatever cursor the first resume named.
