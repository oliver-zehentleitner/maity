### Changed

- Contract (`docs/api.md` §16.5, §6.24, §6.25, §6.26, §1.3, §1.7): the number of aliases per human,
  organisation, agent profile and project is now the instance admin's `max_aliases` in Limits
  (`MAITY_MAX_ALIASES`, default 3, an integer 1–8) instead of a fixed 8. A rename over the value is
  refused with `alias_limit` as before, with `details.limit` the value. Lowering it drops no alias.
  `GET /admin/settings/limits` also counts `names_at_alias_limit`.
