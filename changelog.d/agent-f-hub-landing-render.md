### Added

- hub: the landing page and the legal pages are rendered by the hub as static HTML, with no
  script and no image and a Content-Security-Policy of their own (§16.7, §16.7.1): `/` for a
  visitor without a session while the landing page is enabled (`?lang=`, else `Accept-Language`,
  else the default language; `?as=public` shows it to a signed-in human), `/impressum`,
  `/privacy`, `/terms` and their earlier versions at `/<page>/<version>`. The counters of the
  `stats` section are computed at most every five minutes and published in `GET /landing`.
- hub: a draft of the landing page or of a legal page can be seen before it is saved:
  `POST /admin/settings/landing/preview` and `POST /admin/settings/legal/preview?page=`, then the
  address they return (migration 0093).
- hub: while the `terms` page is set and neither the environment nor the admin gave terms, the
  registration's terms are that page and its version (`source: legal_pages`).

### Changed

- hub: `robots.txt` and `sitemap.xml` follow the landing page and the legal pages that are set;
  the app shell is `noindex` on every path including `/`.
