### Added

- Contract §6.1, §6.4: a card's restricted text, one plain-text value of
  at most 1000 characters on up to 200 cards per project, read and written
  only by the members a new project setting `restricted_access` names
  (`nobody_except` or `all_except`, default closed, changed by a human with
  `project:admin` and a step-up, its list shown only to human admins and
  the set); its own routes `…/tasks/{id}/restricted`, never a card field,
  for a human only from a session in good standing; a `restricted_changed`
  event read only by the set as it stands at the read, outside the owners'
  and admins' see-all, and a notification without the text or the card's
  title; the writer's own texts in their export while they are in the set;
  under `all_except` an agent only in the set with its owner, and every
  way into the set (setting, join — an organisation owner's membership
  made by the hub included — guest raised, by the hub for an organisation
  owner included, isolation ended, an agent's
  owner changed) told to the set by a `restricted_changed` event; under
  `nobody_except` a listed agent leaving the list when its owner changes,
  with a `left` event when it was in the set; `Cache-Control: no-store`
  on the routes, write caps per membership and, for `PUT`, per card, one
  notification per card and human and one set notice per human and
  project in 10 minutes.
