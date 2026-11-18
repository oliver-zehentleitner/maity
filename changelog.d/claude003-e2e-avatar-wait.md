### Fixed

- web e2e: the visitor profile layout check waits for the hero's picture to have its size
  (128 px, 96 px on a phone) before it measures it, so a read right after the page is drawn
  no longer sees 0 px now and then. A picture that never gets the size still fails with
  "the picture is … px". No change to the dashboard itself.
