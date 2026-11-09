### Added

- hub: an API answer to the instance admin's signed-in session carries `Server-Timing`, with
  the number of database statements, their time and the time until the answer starts
  (`db;dur=…, sql;desc="n=…", total;dur=…`). Nobody else gets the header.
- hub: every API request writes its statement count and times to the log
  (`maity_hub.timing`), by route pattern, status and the worker's pid, never the path.
