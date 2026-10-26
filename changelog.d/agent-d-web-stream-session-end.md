### Fixed

- web: a password change or signing out no longer leaves the notifications long-poll to answer
  401: the page cancels it first and resumes after a password change; a 401 on the stream ends it
  instead of retrying
