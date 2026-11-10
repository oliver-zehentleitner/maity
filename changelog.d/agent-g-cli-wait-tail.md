### Changed

- cli: `maity wait` rests out the last seconds of a window instead of
  ending it with a chain of short long-polls, a request or four less per
  window and agent.
