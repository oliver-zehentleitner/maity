### Changed

- e2e: the hub runs with a local attachment store (`MAITY_ATTACHMENT_DIR`), so the attachments
  step uploads an image for real and shows it inline from the hub (#474 is on main).

### Fixed

- web: a link in one's own chat bubble takes the text's colour, underlined: the accent reached only
  4.33:1 on the bubble's background (found by the e2e's accessibility check once images were sent).
