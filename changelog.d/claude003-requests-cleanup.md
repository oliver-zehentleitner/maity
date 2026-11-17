### Changed

- hub: an internal clean-up of the request routes: each single-row helper (the
  holder, the asking instance, the status filter) now goes through its batch
  form, and two helpers that only forwarded are gone. Answers and events stay
  the same. One difference is left, in a race only: a forward or a claim by a
  human who was removed from the project and added again while the call waited
  for the project's lock is now `not_found`, as an answer or a new request
  already was.
