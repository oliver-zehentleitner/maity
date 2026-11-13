### Fixed

- web: a public board's columns, which scroll sideways on a phone, are a
  named region that takes the keyboard focus, so they can be scrolled
  without a mouse also where the board has no cards. The region takes the
  focus on a full board too: tabbing to a card scrolls only as far as that
  card, so the columns to the right of the last one are reached only
  through the region.
