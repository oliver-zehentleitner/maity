### Changed

- hub: `MAITY_WEB_DIR` set and empty now serves no dashboard, the API alone, so the Helm chart's
  `config.dashboard: false` really turns the dashboard off. Before, an empty value counted as
  unset and the hub served its packaged dashboard. This changes only a hub that sets
  `MAITY_WEB_DIR` to an empty value and still expects the default dashboard: leave it unset
  instead. A path that is not a directory still stops the hub, and unset still serves the
  default. The admin's settings overview shows an empty `MAITY_WEB_DIR` as set, with no value.
