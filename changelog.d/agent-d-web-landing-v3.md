### Added

- Landing page (§16.7, #737): `hub/src/maity_hub/landing_assets/landing.js`, the page's one script
  (at most 10 KiB, no request): the theme switch (`data-theme`, kept in this browser), the demo's
  loop while it is on screen (`.demo-on`), the scales as tabs (`.scales-tabs`) and counters counting
  up; nothing of it under `prefers-reduced-motion`. `web/tools/check.py` checks its size, rules and
  that it makes no request.
- Dashboard, admin area, **Landing page**: the **Demo** section (terminal lines of a kind, an
  optional inbox item, exactly three steps) and the **Open source** section (tiles and links), each
  list at its own field path; the fixture hub checks them as §16.7 says.
