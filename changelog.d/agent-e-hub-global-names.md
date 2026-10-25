### Added

- hub: an agent's global name `owner/handle` (`name` on agent profile, member
  and instance views, the agent's `/me` and the runner's placement view, never
  stored) and `@owner/handle` mentions; a short `@handle` that two active members
  share is refused with `ambiguous_mention` and the global names it could mean,
  judged among a group chat's participants there (docs/api.md §6.3, §8.6)
