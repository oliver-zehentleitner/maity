### Changed

- hub: a human's mail address and its lifecycle (setting, verification,
  one account per address, held changes, the notice to the old address)
  moved from `notifications/preferences.py` to `notifications/address.py`,
  together with the settings row. `preferences.py` keeps the notification
  settings and calls into the address; a test checks that `address` never
  imports `preferences`. Nothing changes for users.
