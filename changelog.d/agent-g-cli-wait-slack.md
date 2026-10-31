### Fixed

- cli: `maity wait` leaves the hub 10 seconds to answer each long-poll
  (it used to leave about one second on the last poll of a window), and a
  read that runs out at the end of the window is an ordinary timeout
  (exit 3) without `hub connection lost`; a connection error before the
  deadline still warns and retries.
