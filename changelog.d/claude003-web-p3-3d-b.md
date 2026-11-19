### Fixed

- web: in Korean, the note that none of one's runners offers the project's repository puts the
  object particle after the repository's name in both forms, `{repository}을(를)`, as every other
  particle after a placeholder does; it read `를` only, wrong after a name ending in a consonant.

### Changed

- web smoke (test only): the join whose lists are read after its line was closed is now answered
  for a new profile, and the check also asserts that the form opened since offers that profile
  and that the new seat is handed to the page's seats hook. Removing that branch's redraw now
  fails the check.
- web: the context entry on the one role list says that a project's own roles follow the
  built-in ones in every role picker, read once per view, and that one's own agent is not
  offered an own role based on `ops` (documentation only).
- web check (comment only): the comment on which `const`/`let` a name handed to
  `M.stepUp.run` resolves to now states the rule the code applies.
