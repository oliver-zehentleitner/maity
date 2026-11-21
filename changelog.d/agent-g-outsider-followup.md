### Added

- hub: an outsider of a public project reads its Why view, `GET …/keep-the-why`,
  `…/keep-the-why/export` and `…/keep-the-why/bodies`, while the hub last found
  the project's repository public, as the public page's Why; otherwise
  `not_found`. `max_age=0` keeps the members' rate of one forge read per 30
  seconds per project (§2.3).

### Fixed

- hub: an outsider's member views of a public project carry the picture the
  public page shows in `avatar_url` (`null` while a person's `public_profile`
  is off), not the member address an outsider cannot fetch (§2.3).
