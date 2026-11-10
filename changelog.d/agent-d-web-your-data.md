### Added

- web: Your data on the account (docs/api.md §2.9): **Export my data** saves
  the hub's JSON export; **Delete my account**, confirmed by the handle,
  requests the deletion that the mail's link confirms, and a pending request
  can be withdrawn. Sensitive calls ask for the password or a second-factor
  code where the hub requires it, and are then made again (`js/step-up.js`).
