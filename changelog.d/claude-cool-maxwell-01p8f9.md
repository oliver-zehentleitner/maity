### Fixed

- web: before sign-in the dashboard chooses the language in the landing page's
  order (`?lang=`, then the browser's, then English, where the landing page
  falls back to its default language) and keeps no choice in the browser, so a
  language chosen once no longer makes sign-in and visitor views differ from
  the landing page; a choice made on a page writes `?lang=` into the address,
  and the older stored `maity.language` is removed (tsk-a9n9p6952wwb).
