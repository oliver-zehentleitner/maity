### Added

- hub: every successful answer under `/api/v1/` carries `Server-Timing` with the number of
  database statements, their time and the hub's whole time (`db;dur=…, sql;desc="n=…",
  total;dur=…`). A refusal carries none.
