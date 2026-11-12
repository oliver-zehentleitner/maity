### Fixed

- web: a redraw keeps an `<img>` whose src and other attributes are unchanged,
  so the browser does not abort that load and start it again. An avatar reuses
  a sized URL that is already loaded or in flight, in a bounded map.
