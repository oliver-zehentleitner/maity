### Fixed

- hub: a closed-column cursor whose card id does not encode as UTF-8 (a lone surrogate, which
  JSON can carry) is refused as `400 invalid`, like a NUL or an overlong id, instead of reaching
  the database driver.
