### Changed

- web: the sign-in banner and the authenticator banner start their reads before the page
  is drawn instead of after it, on every page, so they no longer wait for the page's own
  reads (the board's took about 1.2 s cold). The banners look and act as before.
- web: the sign-in banner reads only the active sessions (`GET /auth/sessions`), not the
  ended ones of the last 30 days (16–18 kB) on every page. It reads the ended ones only
  when an active session was approved by a session that has ended, the one case in which
  an ended sign-in still shows in the banner.
