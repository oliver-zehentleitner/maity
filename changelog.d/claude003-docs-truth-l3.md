### Fixed

- docs: the operator docs and the front page say what the hub does (docs truth sweep L3,
  tsk-w7mgs87b4gya). The Helm chart's README says the image is published for every release tag,
  that the forge probe is there (its `values.yaml` comment too), that `config.dashboard: false` no longer switches the dashboard
  off (the hub then serves the one its package carries; the chart has no API-only setting), that
  the read limit counts in each hub process, and that no `maity-hub` command migrates down. The
  runner server setup says the bootstrap ends with a `next:` line and that step 3b comes first.
  The front page, in all ten languages, no longer says the hub sums the token counts a supervised
  run reports: it does not yet.
