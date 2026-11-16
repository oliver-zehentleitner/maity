### Changed

- Hub: a release card takes the PEP 440 version its tag carries (`0.1.0a4`, `0.1.0rc1`) beside
  SemVer, so the probe finds the tag `v0.1.0a4`. Junk, `.post`, `.dev`, epochs, local versions
  and non-canonical spellings are refused with `details.fields.release.version: not_a_version`,
  which replaces `not_semver`. Versions are compared as text: `0.1.0-alpha.4` and `0.1.0a4` are
  two releases.
