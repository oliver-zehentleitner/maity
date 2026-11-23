### Security

- hub: every `maity-hub` command (`migrate`, `serve`, `quickstart`, `owner create`, the
  operator commands, `loadtest`, `attachments copy-to-s3` and its bucket clean-up) names a
  database error the way the log does, by its class, cause category and codes, and no longer
  prints the driver's message, which can quote the connection string with the password.
