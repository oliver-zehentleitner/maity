### Added

- hub: the right to moderate a jour fixe series takes effect only with both the agent's owner and a
  keeper of the series (`POST …/series/{jfs}/moderators` answers `202` with the consent requests
  when one is missing); a right ends when its membership is removed or isolated or its agent's owner
  leaves; the grants the upgrade left pending get their owner's consent request; a round nobody
  could moderate is an inbox item for the series' keepers; the moderator is picked by minutes
  online, humans included (docs/api.md §20.2, §20.9; part 2 of 3).
