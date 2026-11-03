### Added

- hub: `GET /site/chrome` serves the header and footer of the public pages as one model in one language (§16.7.5). The landing page now draws its own header and footer from that model, so its legal links carry `?lang=` as well (tsk-jc5y1bsjsfbf).

### Fixed

- hub: a social link counts as `rel="me"` only when `/@` is in the path of its address. `/@` in the query or the fragment no longer makes it one, on the landing page or on the legal pages (§16.7.5).
