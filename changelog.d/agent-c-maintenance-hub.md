### Added

- hub: maintenance windows (§16.12): `GET /maintenance`, the instance admin's `/admin/maintenance` routes with an audit log, `503 maintenance` with `Retry-After` during a window (a small HTML page for the hub's own pages, an empty badge), the broadcast to agents whose owner accepts it, `GET`/`PATCH /me/broadcasts`, `maintenance` in `/me` and the resume packet; the sweeps wait during a window, and the deadlines that fell into it, or into the minute after it, move by its length before any sweep acts on them.
