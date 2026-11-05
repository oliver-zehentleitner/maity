### Fixed

- web: the page's language chosen on `/register` before sign-in now stays the choice when the page
  was reached with `?lang=` (as the frame's links do) instead of jumping back to that language; a
  choice on `/login` and `/register` also writes the new tag into the address's `?lang=`, so a reload
  keeps it
