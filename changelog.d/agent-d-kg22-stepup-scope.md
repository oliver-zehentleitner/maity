### Fixed

- web: the step-up check of `make check` ties a wrapper to the binding it is given: a second,
  unwrapped binding of the same name in the file, or a `call:` property also called outside the
  question, is a finding. A path part it cannot read may stand for several segments, and a body
  key behind a variable is read (tsk-4zrnkb3gh6mq).
