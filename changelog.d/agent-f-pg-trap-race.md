### Fixed

- hub: `scripts/with_postgres.sh` sets its signal traps before it starts the
  command, so a TERM, INT or HUP that arrives just as the command starts is
  passed on to it, instead of ending the script while the command runs.
