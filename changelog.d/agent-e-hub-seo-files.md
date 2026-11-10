### Added

- hub: `GET /robots.txt` and `GET /sitemap.xml` (§16.7): with the landing page enabled, crawlers may read the root and
  the files it is drawn from and the sitemap lists the root; without it they are asked to fetch nothing but the
  root, which answers `X-Robots-Tag: noindex`, and the sitemap is `404`. Cached for an hour, no cookie; the join
  host answers both `not_found`.
