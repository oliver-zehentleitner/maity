### Security

- hub: one mail that cannot be built no longer stops the mail outbox. Each
  row is built before it takes a place in its kind's hourly budget; a row
  that cannot be built, or whose handling fails in another way than the
  database, is marked `failed` with its text and headers cleared, logged
  without its content, and the outbox goes on with the next mail. Rows left
  in `sending` by an earlier version are taken again once their claim
  lapses and are sent or failed under the new rule.
- hub: every mail header value is one line of plain text: each run of
  control and line-break characters (Unicode Cc, C1 such as U+0085
  included, Zl and Zp) becomes one space, in subjects built from project
  names, display names and titles as everywhere else.
- hub: a project's `name` and an agent profile's `display_name` (also when
  a join or a placement creates the profile, and on `maity-hub owner
  create`'s `--display-name`) refuse
  control and line-break characters (Unicode Cc, Zl, Zp) with `invalid`,
  `details.fields.<field>: "control_character"`; human and organisation
  display names refuse the same characters (`invalid`), not only ASCII
  ones.
