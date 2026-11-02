### Changed

- The hub's own words moved to one catalog per language, `words/<lang>.json`, so a new language needs only a file. Texts read as before; a key without a translation reads in English.

### Fixed

- A person whose language is `zh-Hans` now gets the registration mail in it once it exists; the tag was cut to `zh` before.
