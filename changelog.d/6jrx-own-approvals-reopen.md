### Changed

- hub: tests now hold two own-approvals cases the hub already decides (docs/api.md §2.3,
  §6.4, §6.6): an agent that counts as outside does not close a merged card blocked in
  review through a reviewing role, and a report with a new head on a `done` card of
  outsiders' work whose pull request is merged or closed is refused as on any `done` card,
  which stays `done`. No behaviour change.
