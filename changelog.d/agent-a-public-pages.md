### Added

- docs: §16.9 public pages: with `MAITY_PUBLIC_PAGES` on, a project whose namespace owner sets `public_page` and a person who sets `public_profile` get static HTML pages at `/p/<owner>/<slug>` and `/u/<handle>`, without script, listed in the sitemap and allowed in robots.txt; nothing is public by default. The operator chooses rendering on change or on an interval (`MAITY_PUBLIC_PAGES_RENDER`, `MAITY_PUBLIC_PAGES_INTERVAL_HOURS`); taking a page down is always immediate.
