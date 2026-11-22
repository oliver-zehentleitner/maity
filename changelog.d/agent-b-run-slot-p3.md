### Fixed

- tools: `tools/run_slot.sh` also runs the command without a slot when a slot file cannot be
  opened in bash's POSIX mode (`POSIXLY_CORRECT`), where it ended silently with exit 1 before;
  a slot holder whose `.who` file is empty or missing shows as `unknown` in the waiting message
  (tsk-deaaanqsq5e2).
