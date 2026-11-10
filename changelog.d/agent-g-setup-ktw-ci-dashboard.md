### Added

- hub: the setup options `keep_the_why_ci` and `keep_the_why_dashboard` (default `true`, only with
  `memory.provider: keep-the-why`) and `dashboard_path` (default `keep-the-why-dashboard`, checked for its
  shape, `null` while the dashboard option is off) on `POST /projects`, each option with its setup card (§6.21);
  migration 0107 writes them as `false`, `false` and `null` into the `setup` of existing projects
