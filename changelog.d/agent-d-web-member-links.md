### Changed

- web: every member a view names is a link to their row in Members, with the full name as
  tooltip, through one helper (`M.dom.memberRef`): the overview, the inbox, chats and group
  chats, project messages, the ticker, the members list, agent cards and the organisation; a
  member the project does not list, and anyone in a read-along view, is plain text

### Fixed

- web: an attachment refusal whose message is not a string leaves it out instead of showing
  "[object Object]"
