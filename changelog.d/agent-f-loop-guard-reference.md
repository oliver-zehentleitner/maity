### Fixed

- hub: the loop-lag guard in the `hub-load` job measures the apps' event loops against an idle
  loop beside them, not against a fixed 250 ms: a GitHub runner made even an idle loop 247–251 ms
  late, which turned main red since the guard came (tsk-v874y63b4z8p). An app's loop fails when
  its worst tick runs more than 150 ms later than the idle loop's, or when it is late by more than
  20 ms on average (`MAITY_LOOP_LATE_MARGIN_MS`, `MAITY_LOOP_LATE_AVG_LIMIT_MS`), or when one
  callback on it spends more than 50 ms of the loop thread's CPU time, the garbage collector's
  left out (`MAITY_LOOP_CALLBACK_CPU_LIMIT_MS`): a computation holding the GIL delays the idle
  loop as much and passed the margin. The job prints the windows of a passing run too.
