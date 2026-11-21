### Changed

- hub: `GET /admin/registrations`, `GET /admin/reports` and `GET /me/reports` read the people,
  the projects' names, the reporters' handles, the agents and the public pages once for the
  whole page instead of once per row, so they cost the same statements for 3 rows as for 30
  (also with public pages served); the three routes leave the known exceptions in
  `hub/tests/list_rows.py` (tsk-sn8keg63p6k6).
