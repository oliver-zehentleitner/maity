### Fixed

- hub: `GET /health` no longer loads every migration file on each request; the migration head is read once when the hub starts
