### Security

- cli: `maity runner` reads files on the agents' side (a clone's
  `.git/config`, logs and state) as regular files only, without following
  links or waiting, up to a fixed size and within a time limit, and
  inspects an existing clone only in the task that starts its agent.
- cli: `maity runner` holds each placement's log to
  `limits.log_keep_bytes` (keeping the newest output), and a status file
  that cannot be written while serving is retried with backoff instead of
  ending the service.
