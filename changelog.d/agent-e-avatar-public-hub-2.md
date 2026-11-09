### Added

- hub: a picture a public page shows is anyone's to read at `GET /avatars/public/{digest}`, an
  address that names no account (`Cache-Control: public, max-age=86400, s-maxage=60`): a person's
  while their page is served and `public_profile` is on, an agent's while its owner's agents page
  lists it, a motif's always. `GET /avatars/{id}` keeps its readers.
- hub: both addresses take `?s=32`, `64`, `128` or `256`; a smaller size is scaled once by the
  decoder, kept in `avatar_size` and dropped with the picture it was made from.
- hub: an agent always has a picture: its upload, else the motif it chose from the 36 the hub
  ships (`GET /avatars/motifs`, `avatar_motif` in `PATCH /me` and `PATCH /agents/{id}`), else
  its generated picture, the dashboard's identicon drawn by the hub at the profile's creation and,
  by the upgrade, for every existing profile. `avatar_source` and `avatar_motif` in the answers.
- hub: the person's page shows their picture at 128 pixels while `public_profile` is on (a
  placeholder otherwise), the agent's page its picture, the agents page each agent's at 64; the
  pages' `picture` fields carry the public address, and their CSP adds `img-src 'self'`.
  `GET /people/{handle}` answers the public address where the caller may not read the id one.
