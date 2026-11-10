### Fixed

- cli: a review's text check no longer reads a contrast ratio (`5.60:1`,
  `4.5:1`, `3:1`) as a file and line. A Keep-the-Why id has to be the full
  UUID as it stands at the head; any other hyphenated hex token that starts
  with eight hex digits and contains a letter `a`–`f` is refused. A cited
  test name, including `path::name`, has to be a `def` or `async def` of
  that name at the head, and the path has to be a file or a directory there.
