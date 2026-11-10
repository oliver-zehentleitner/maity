### Changed

- docs/api.md §11.4, §6.22, §16.9: the one exception to what a grant's read may show without
  sign-in, the bare number of merged pull requests while that read found the repository public;
  a public page now counts a merge whichever source read it, and the ticker's scan flags
  `merge.public` from its own read's answer (`base.repo.private`), no longer from the token.
