### Fixed

- runner: the dev venvs' code comment, test and Keep the Why entry no longer
  call pip's wheels-only environment a second hold. It does not stop a
  source build for an option on a lock line; the lock check refusing that
  line is the one hold. A test comment now says "the runner's python3", as
  the code and docs do.
