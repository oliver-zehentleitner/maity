### Fixed

- hub: revoking or removing a runner, re-pairing it, deleting its owner's account and
  suspending its owner now lock the runner's live credential before the runner row, the
  order every call of the runner itself takes them in. On PostgreSQL and MariaDB a revoke
  and a runner's call at the same moment could deadlock, and the runner's `hello` then
  failed; `hello` now also runs again after such a conflict. A suspension locks the same
  projects a runner's stop locks, from one shared rule.
