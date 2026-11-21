### Added

- hub: an outsider of a public project reads its Why view, `GET …/keep-the-why`,
  `…/keep-the-why/export` and `…/keep-the-why/bodies`, while the hub last found
  the project's repository public and the forge, asked again at least every 10
  minutes, says it is public; read without the owner's grant into a cache of
  their own, as the public page's Why. Otherwise `not_found`, before the query
  is read. `max_age=0` forces at most one read per 30 seconds per project (§2.3).

### Fixed

- hub: an outsider's member views of a public project carry the picture the
  public page shows in `avatar_url` (`null` while a person's `public_profile`
  is off), not the member address an outsider cannot fetch (§2.3).
