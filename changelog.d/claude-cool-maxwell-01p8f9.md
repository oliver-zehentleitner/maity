### Fixed

- web: before sign-in the dashboard chooses the language as the landing page
  does (`?lang=`, then the browser's, then English) and keeps no choice in the
  browser, so the landing page, sign-in and visitor views no longer differ for
  the same visitor; a choice made on a page writes `?lang=` into the address,
  and the older stored `maity.language` is removed (tsk-a9n9p6952wwb).
