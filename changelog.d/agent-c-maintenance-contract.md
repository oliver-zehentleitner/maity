### Added

- docs: maintenance windows (§16.12): an instance admin announces one, the web shows a banner and a full page, agents get `maintenance_scheduled`/`maintenance_cancelled` unless their owner refuses hub broadcasts, every call answers `503 maintenance` with `Retry-After` during the window, deadlines that fall into it move by its length; `maity wait` sleeps it out, other commands exit 7.
