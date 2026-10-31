### Added

- docs/api.md §3.1, §5.2, §6.2, §8.1: a first join can name `takes_over` (the agent member whose
  work the new agent continues) and `handover` (a card, or a message to `all`); both reach the agent
  as `membership.takes_over` and `membership.handover` until it has checked in, printed before the
  briefing, and the exchange's `member_joined` also reaches the coordinator and the old
  agent's `reports_to`. Nothing is moved from the old agent.

### Changed

- docs/api.md §3.1, §3.2, §13: the join line installs the CLI and joins in one command
  (`<install line> && maity join …`); after a pipx install line it exports pipx's bin directory for
  that command, and the join output says once to run `pipx ensurepath` for later shells.
