### Added

- docs/api.md §6.21: project memory and setup cards — `memory.provider`
  (`none` or `keep-the-why`, the default) on `POST /projects` and `PATCH`,
  with `keep_the_why` kept as its readable alias (§6.1); the prefilled
  setup options `setup: {keep_the_why_init, keep_the_why_badge,
  maity_badge}`, each a card of the new kind `setup` (§6.4) the hub opens
  at creation or when the repository is set — `open`, at the repository
  root, a pull request as the acceptance, never a direct push — with the
  titles fixed verbatim; `setup` in the resume packet (§5.2) and a `Setup
  waits` block in `maity resume` (§13) while a setup card is not done;
  `maity_badge` sets `policy.badge` to `members` at creation (§6.20); the
  create-project form's **Project memory** dropdown and checkboxes.
