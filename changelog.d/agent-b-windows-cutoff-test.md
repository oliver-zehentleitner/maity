### Fixed

- cli tests: the test hub for cut-off answers reads the whole request, including a POST's
  body, before it answers, and after the answer waits up to 2 s for the client to close.
  On Windows a close with request bytes unread sent a reset that dropped the cut answer,
  so `test_an_exchange_names_an_answer_that_breaks_off` saw "cannot reach" (WinError 10053)
  instead of "broke off" now and then. No change to the CLI itself.
