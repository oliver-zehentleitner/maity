### Fixed

- web: **Export my data** and the site download failed in every browser with
  "h(): href is neither a route nor an https URL". They save their file again.

### Added

- web e2e: a round on a second hub with an instance key and a mail catcher: the
  test mail arrives, and an older session's export asks for the TOTP code.
