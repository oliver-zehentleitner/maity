### Added

- web: the "Restricted access" setting in a project's settings, for a human with `project:admin`:
  closed, only the members ticked, or every member but those ticked, each agent with its owner;
  a change that widens the set is confirmed first, with how many cards have a text (from a
  closed setting, that texts written before stay stored) and who newly reads them, and saved
  after a step-up. A human in the set without `project:admin` reads the setting on their own
  settings page.
- web: the "Restricted" box on a card, for members in the restricted-access set only: the card's
  restricted text as plain text, edited and cleared with its version, its changes listed by who
  and when, kept in the page's memory only.

### Fixed

- web: the restricted-access set's notice in the bell opens the project's settings and is marked
  read like any notice, instead of opening one's own notification settings and staying unread.
