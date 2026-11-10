### Changed

- hub: the instance's landing page is a page per language in sections (`hero`, `stats`, `steps`,
  `scales`, `faq`, `cta_band`, `text`, `activity`, `profiles`, `explore`, `collab`) with a footer,
  checked field by field (`pages.de.sections.2.items.0.title`); `GET`/`PATCH
  /admin/settings/landing` and the public `GET /landing` carry `default_language`, `pages` and
  `footer`. The old Markdown body, title and call to action are gone; migration 0090 carries them
  over as the `en` page. The body of both settings' `PATCH` may be 512 KiB.

### Added

- hub: the legal pages (imprint, privacy notice, terms), per language, with every version kept:
  `GET`/`PATCH /admin/settings/legal` (one page per call, 20 changes per page per day) and the
  unauthenticated `GET /legal`.
