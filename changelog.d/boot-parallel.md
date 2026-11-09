### Changed

- web: the dashboard's first drawing asks the session together with the
  maintenance window instead of after it, its answers handled in the same
  order as before; `/me` still follows the session (tsk-y8gkq1kvt63c).

### Fixed

- web: an older session read that comes back after a newer one, a 401 above all, no longer switches the newer session's language back; the invitation and registration pages get no second session read (tsk-y8gkq1kvt63c).
