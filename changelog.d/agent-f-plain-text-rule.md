### Changed

- hub: names and short texts follow one rule (docs/api.md §1.7.1): a
  project's name, every display name, an invitation's note, a card link's
  URL and label, a person's website and a project's links, a review's
  subject and a human's preferences refuse control, format (zero-width,
  direction, tag), surrogate and line-separator characters; a note and the
  preferences keep the line feed and the tab, and a name keeps an emoji
  sequence (a zero-width joiner between two emoji, a variation selector
  right after one). Each field answers with the
  reason it already had (`control_character`, `not_a_url`, `format`); an
  invitation note's refused character is now `control_character` rather
  than `invalid`.
- hub: where the hub writes a project's name into a text or Markdown line
  for agents (the join page, the rules document, the requests it files),
  a name stored before the rule stays on one line.

### Added

- hub: the invitation page's answer names the inviter's handle as well
  (`invited_by.handle`, §3.4).
- web: the invitation page shows the inviter as "display name (@handle)"
  and sets the project's and the inviter's names apart from the sentence
  around them.
