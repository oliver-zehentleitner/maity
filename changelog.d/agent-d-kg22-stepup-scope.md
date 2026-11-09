### Fixed

- web: the step-up check of `make check` ties a wrapper, and a local helper that hands the call
  on, to the declaration of its name nearest the call in the blocks around it (the last
  function declaration of that block, else the last `const` or `let` before the call): a second,
  unwrapped binding or helper of the same name elsewhere, or a `call:` property also called
  outside the question by a name the check reads, is a finding. Other binding forms are not
  resolved. A path part it cannot read may stand for several
  segments, and a body key behind a variable is read where the name is declared by `const name =`
  or `let name =` in the blocks around the call. It reads text, not the program, and checks only
  the forms web/context/views.md lists; any other is not checked (tsk-4zrnkb3gh6mq).
