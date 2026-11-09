### Fixed

- web: before sign-in the dashboard takes the landing page's own language from
  `GET /site/chrome`, read once per page, so the landing page, sign-in and
  visitor views agree also where the landing page has fewer than ten
  languages or another default language; a choice made on the page comes
  first, and a failed or late read falls back to `?lang=`, then the
  browser's language, then English (tsk-jh94ax9pphxs).
