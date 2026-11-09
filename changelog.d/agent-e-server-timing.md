### Added

- hub: the instance admin's signed-in session gets `Server-Timing` on every answer under
  `/api/v1/`, with the number of database statements, their time and the hub's whole time
  (`db;dur=…, sql;desc="n=…", total;dur=…`). Nobody else gets the header.
- hub: every API request writes its statement count and times to the log
  (`maity_hub.timing`), by route pattern, status and the worker's pid, never the path.
