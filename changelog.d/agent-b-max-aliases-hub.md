### Added

- Hub: the instance setting `max_aliases` in `GET, PATCH /admin/settings/limits` (`MAITY_MAX_ALIASES`,
  default 3, 1–8, no `unlimited`) and the read-only `names_at_alias_limit`. Renames of humans,
  organisations, agent profiles and projects read it, and `alias_limit` names it in `details.limit`.
  An id over a lowered value keeps every alias and may still take one of its own names back.
