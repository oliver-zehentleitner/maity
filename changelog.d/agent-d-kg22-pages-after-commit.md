### Changed

- hub: a change that touches a public page (docs/api.md §16.9) renders it once the change has
  committed, in a transaction of its own; a change that takes something off a page still deletes
  the page, and the pages that show it, in its own transaction. One target's render may take at
  most `MAITY_PUBLIC_PAGES_RENDER_SECONDS` (default 2) and a starting process renders pages for
  at most `MAITY_PUBLIC_PAGES_STARTUP_SECONDS` (default 30); a longer render takes the pages off
  as a failed one does, and the pages a start did not reach are off until a worker renders them
  right after.
