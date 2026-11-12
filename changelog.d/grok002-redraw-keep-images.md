### Fixed

- web: a redraw keeps an `<img>` whose src and other attributes are unchanged,
  so the browser does not abort that load and start it again. Each place an
  avatar is shown gets its own image for a sized URL that is already loaded
  or in flight, at the size that place asked for. A node that is on the page
  is not moved. The reuse map drops only a loaded image that has left the page.
