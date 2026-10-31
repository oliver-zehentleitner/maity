### Changed

- docs/api.md §20.2, §6.1, §20.9: the jour fixe's default moderator is `manager_agent`, the first
  present agent with the role `manager`; the admin agents follow only when no manager agent is
  present. `jour_fixe_moderators` lists manager agents; manager and admin agents may set the order.
  `admin_agent` is gone (alpha: no alias; a stored `admin_agent` is migrated to `manager_agent`).
