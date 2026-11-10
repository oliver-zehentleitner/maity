### Added
- web: the legal pages (each page's languages) and the registration
  settings can be imported and exported as JSON, as the landing editor
  can. A legal page's import is checked by its preview call; a
  registration import fills the form. Nothing is saved until Save.

### Changed
- web: a preview while the JSON field holds text that was not loaded
  into the editor says so instead of opening and closing a tab, in the
  landing editor too.

### Fixed
- web: saving or taking down a legal page asks for the second factor
  where the hub wants it (§2.8.4), instead of failing with
  `step_up_required`.
