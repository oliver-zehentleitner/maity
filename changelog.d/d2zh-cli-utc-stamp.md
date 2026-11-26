### Changed

- The CLI and runner share UTC timestamp formatting and parsing. Output uses a four-digit
  year, whole seconds and a trailing `Z`, including for years below 1000. Watch still
  requires the exact wire format. The keeper now also requires it when reading a saved
  `checked_at`. Lowercase `t` or `z` and single-digit fields in older noncanonical
  values give an unknown age and can trigger an immediate daily tool check. The keeper
  writes canonical timestamps. The hub client's server-time parser now requires an
  explicit time zone for clock-skew correction.
