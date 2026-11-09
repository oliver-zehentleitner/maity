### Fixed

- web: the step-up check of `make check` ties a wrapper, and a local helper that hands the call
  on, to the binding seen at the call: a second, unwrapped binding or helper of the same name, or
  a `call:` property also called outside the question by a name the check reads, is a finding. A path part it cannot read may stand for several
  segments, and a body key behind a variable is read where the name is declared by `const name =`
  or `let name =` in the blocks around the call. It reads text, not the program, and checks only
  the forms web/context/views.md lists; any other is not checked (tsk-4zrnkb3gh6mq).
