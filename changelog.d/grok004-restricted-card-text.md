### Added

- Contract §6.1, §6.4: a card's restricted text, one plain-text value of
  at most 1000 characters on up to 200 cards per project, read and written
  only by the members a new project setting `restricted_access` names
  (`nobody_except` or `all_except`, default closed, changed by a human with
  `project:admin` and a step-up); its own routes `…/tasks/{id}/restricted`,
  never a card field; a `restricted_changed` event and notification to that
  set only, without the text.
