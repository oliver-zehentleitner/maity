### Changed

- cli: version 0.1.0a7 for PyPI, with `maity ask --wait` (a question with `--task` blocks the card only then,
  or when it is a consent), `maity task restricted`, `maity memory delete` and `maity memory add -` from stdin,
  a maintenance window slept out, `maity wait` retrying a 429 and taking its timeout from
  `MAITY_WAIT_TIMEOUT`, `maity report` showing the pull request's title and working without `gh`, `maity say`
  checking a review's names and quotes, more in `maity resume` (languages, preferences, unread chats of other
  projects, whom a lead leads), the join option for subagents, a leading byte order mark dropped from every
  text input, `maity report` checking a branch's upstream before git reads it,
  git and `gh` taken only from an absolute `PATH` entry, and a hardened runner.
