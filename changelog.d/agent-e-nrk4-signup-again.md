### Added

- hub: the registration link's page offers **Register again** after a wrong password and on
  an expired or voided link, with the sentence that the newest mail's link replaces the
  earlier one. After a wrong password the address goes to the sign-up page in a short
  cookie (`maity_register_again`, `Path=/register`), never in its address (§2.7.1).
- web: `/register` fills the address in from that cookie, reads it once and removes it.
- hub, web: wherever a person picks or changes a handle (the registration link's page, one's
  own handle, an organisation's, an agent's), the rule stands beside the field and an
  upper-case letter is said while it is typed ("lowercase only"), before anything is sent.

### Fixed

- web: renaming one's own handle no longer lower-cases what was typed without saying so; an
  upper-case letter is refused locally with the rule.
