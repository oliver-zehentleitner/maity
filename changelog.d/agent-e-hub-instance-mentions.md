### Added

- hub: instance mentions `@handle#id` and `@owner/handle#id` (§8.6, §6.17) — the
  stored mention carries `instance`, the ping goes to that instance only (its
  `instance:` token in messages, `mentioned` and `note_added`, and the group-chat
  wake), and an id that is no active instance of that member leaves the whole
  text plain; an ambiguous short handle is refused with a suffix too; `to`
  naming the team does not cover an instance mention, whose token is added on
  top (§8.2)
