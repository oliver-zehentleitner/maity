### Fixed

- cli: a review's text check no longer reads a contrast ratio (`5.60:1`,
  `4.5:1`, `3:1`) as a file and line. A Keep-the-Why id has to be the full
  UUID as it stands at the head; a shorter hyphenated form, including a
  last group cut short of twelve hex digits, is refused. A cited test name
  has to be a `def` or `async def` of that name at the head, not a comment.
