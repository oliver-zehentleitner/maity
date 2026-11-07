### Added

- hub: a card's restricted text (docs/api.md §6.1, §6.4), part two: `settings.restricted_access`
  set by a human with `project:admin` and a step-up, sent whole, every refusal named
  (`unknown_mode`, `too_many`, `duplicate`, `not_a_member`, `guest`, `owner_not_a_member`),
  served per reader (`members` and `cards_with_text` to admins and the set, `{mode, included}`
  to everyone else, `null` without the key), `project_updated` shaped the same way at read;
  `restricted_changed` for every change of a text to `restricted:<task id>`, read only by the
  members on its list that are in the set at the read, never through the see-all, waking the
  agents in the set but the writer; `restricted:set` with `entered` when a setting, a join, an
  invitation, an organisation's owner, a raised guest or a lifted isolation lets members in,
  and `left` with the owner-change helper under `nobody_except`; the two `inbox` notices at
  most once in 10 minutes, listed only while the event is read; the `guide_role` sentence for
  an agent in the set.
