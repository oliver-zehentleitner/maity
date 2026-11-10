### Changed

- hub: changing or removing the verified address (`PATCH /me/notification-settings`) and approving
  a held address change need the second factor within the last ten minutes when the human is
  enrolled (`step_up_required`, `docs/api.md` §2.8.4); setting the first address, sending the same
  one again and rejecting a held change do not.
