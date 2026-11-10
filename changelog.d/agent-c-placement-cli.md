### Added

- cli: `maity placement list|start|stop|restart` and `maity runners` (runner slice R6a,
  `docs/api.md` §15.6) — for agents with `agents:propose`: start an existing member on a
  runner (under consent the request id is printed), stop with `--grace`, restart, list;
  an agent is named by handle or id, a placement by id (an exact id wins, ambiguity is
  refused); `restart --rejoin`; the project's runners with
  presence, agents running and available tools.
