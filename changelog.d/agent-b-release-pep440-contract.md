### Changed

- Contract: a release card's `version` (§6.7) is the version its tag carries without the `v`:
  SemVer as before, or the canonical PEP 440 form with three numbers and an optional `a`, `b`
  or `rc` pre-release (`0.1.0a4`). `.post`, `.dev`, epochs, local versions, a leading `v` and
  spellings PEP 440 would normalize are refused with
  `details.fields.release.version: not_a_version`. The probe looks for the tag `v{version}`
  as given; versions are compared as text, so `0.1.0-alpha.4` and `0.1.0a4` are two releases.
