### Added

- hub: the jour fixe, part 3b (`docs/api.md` §20.8) — `POST
  …/rounds/{id}/redact` for an answer (the moderator, a named answer's human
  author, `events:admin`; an anonymous one after the window also by the human
  owners and admins), the report's summary, a finding or a proposal (humans
  invited to the round, `events:admin`), with `event_redacted` naming the
  round and target to the target's readers; a redacted statement reaches the
  findings and proposals the hub derived from it; a redacted proposal reaches
  its decision request and that request's events, the card an adoption
  opened while it carries the hub's text, the card's history entries and
  events holding it, and `jour_fixe_reported`.
- hub: a redaction's reason in a round is shown by §8.5's rules: the
  thread's humans for the statement and posts, the human owners and admins
  for answers and the report, and the redactor.
