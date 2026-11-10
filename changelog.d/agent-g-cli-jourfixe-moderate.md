### Added

- cli: the jour fixe moderation commands (§20): `maity jourfixe statement` and `report` send the
  body of §20.5 and §20.6 from a file or stdin and print the ids and the triage the hub gave
  them; `post` and `step` for the exchange; `start` prints a refused start's reason with exit 1;
  `moderators` shows the resolved order or sets it with `--set`/`--reset` and a reason.
  The jour fixe lines in `maity wait` and `maity resume` name the command each waking event
  asks for (`statement`, `post` with the step's kind, `report`).
