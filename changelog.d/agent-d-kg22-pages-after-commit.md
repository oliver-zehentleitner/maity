### Changed

- hub: a change that touches a public page (docs/api.md §16.9) renders it once the change has
  committed, in a transaction of its own; a change that takes something off a page still deletes
  the page, and the pages that show it, in its own transaction. A render of one target that takes
  longer than `MAITY_PUBLIC_PAGES_RENDER_SECONDS` (default 2) takes its pages off as a failed one
  does, and a starting process takes up no further target after
  `MAITY_PUBLIC_PAGES_STARTUP_SECONDS` (default 30): the targets it took up are rendered to the
  end, so the setting does not bound the whole start, and the pages the start did not reach are
  off until a worker renders them right after.
