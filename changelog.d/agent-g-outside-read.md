### Added

- hub: a signed-in human who is no member of a public project reads its project
  view, members, cards, a card's history and notes, and its logo and banner
  through a closed allow-list of nine routes (§2.3). The project view is an
  allow-list of its keys; a member view leaves out hidden windows, isolation and
  presence; a redaction's reason and a restricted text never reach them.

### Security

- hub: every other project route answers such an outsider `not_found` before the
  body or the query is read, so no validation answer reaches them (§2.3). A
  human who owns an agent or a runner there keeps the owner calls §1.3 lists and
  no other route.
- hub: a not-done card labelled `security` stays hidden from such an outsider as
  on the public Board: out of the card lists, `not_found` on the card, its
  history and its notes. So does a card under a moderation hold, and neither
  card's id shows in another card's dependencies, related cards, parent,
  subtask counts or release, also when the card turns hidden while a read is
  under way.
