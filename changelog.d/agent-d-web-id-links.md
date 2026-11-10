### Added

- web: **ids in text are links** (tsk-dcj6qwjxc9cq): in requests, chat and project messages, card
  titles, checkpoints, reports and the ticker, `tsk-…` opens the card on the board (new route
  `#/p/<slug>/tasks/<id>`, the board with the card marked), `req-…` the request
  (`#/p/<slug>/inbox/<id>`), `agt-…`/`hum-…` the member, and `#123` the project repository's issue
  or pull request on GitHub; linked by shape only, never looked up; code stays plain; an inbox
  entry's title ids are offered under **In the title**
