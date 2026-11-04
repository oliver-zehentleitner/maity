### Changed
- web: the sign-in and `/register`, wherever they are drawn without a session (`/login`, the
  root after a sign-out, an address of the app without a stored public page), stand in the
  landing page's header and full footer, read from
  `GET /site/chrome` in the page's language and laid out by the hub's `landing.css` and
  `public-pages.css` (gj6k's design, §16.7.5). The pitch fills the dark panel beside the form,
  its title is the form's heading, and the buttons are the landing page's. A failed read draws the
  page without the frame, with the app's bar and the legal links as before. The stylesheets are off
  on every other view.
- web: under the frame's footer the product line is not drawn, nor while a signed-out
  drawing of the sign-in or `/register` waits for its `GET /site/chrome` (req-5k1gvfsmcg9k);
  a page drawn without the frame and every other view show it. `docs/api.md` §16.13 says so.
- web: the fixture hub answers `GET /site/chrome` from its landing and legal settings.
- web: the #1268 follow-ups: an unused variable removed from the card panel, and KTW 5260ca07
  names its source, the known gap of an open edit (tsk-wvf8s7f44vz7) and more revisit triggers.
