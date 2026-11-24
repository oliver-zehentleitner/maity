### Fixed

- runner: a Codex start ends the placement's updater loop before it stops
  the app-server daemon. `daemon stop` leaves the loop running, and the
  loop would otherwise start a replacement daemon with the first start's
  environment. The runner finds the loop only by the pid Codex records in
  that `CODEX_HOME`, and sends TERM only once that process is shown to be
  the loop. A closed Codex placement gets the same steps before its scratch
  is removed.
