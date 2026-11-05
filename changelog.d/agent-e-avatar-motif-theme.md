### Changed

- contract: every agent motif carries a `theme` (the first set is `classic`), motif names
  are unique across themes, and `GET /avatars/motifs` lists them ordered by theme so a
  client can group them; an agent still chooses one motif by name (§6.10). The dashboard
  heads a theme with its catalogue's `avatar.motif.theme.<theme>`. The hub and web
  implementation follow separately.
