### Added

- runner: the watch (§15.14). On each placement whose hub carries `session`, the runner
  looks when the agent's session has been not listening for `not_listening_grace_minutes`
  (counted from this run's start at the earliest) or no session joined within
  `join_within_minutes` of the start, gathers fixed signals (the process and its exit
  code, what runs below the harness, the login probe) and reacts by cause: one restart
  that resumes the session (`exited`/`hung` with `not_listening` or `never_joined`), one
  nudge per quiet spell, a wait for the provider limit's reset, or `failed`/`auth` for a
  login that needs a person. Past `auto_restarts` restarts within `retry_window_minutes`
  it holds the placement as `failed`/`hung`. It ends nothing while someone is attached and
  leaves paused and dormant agents alone, the own idle check included. After a runner
  restart or upgrade, a session it finds still running is first watched for one full grace.
  New settings under `[limits.watch]` (docs/runners.md), listed by `maity runner check
  --explain`.
- runner: a status report carries `finding` (§15.7) once per diagnosis, with the runner's
  own notes about the placement as its log, in hub time; a pickup or join the hub refuses
  with a code adds a `pickup_refused` finding to the `join_failed` report.

### Security

- runner: before a finding leaves, its log lines are scrubbed: forge tokens (GitHub,
  GitLab), provider keys (Anthropic, OpenAI, xAI, Google, AWS), Slack tokens and
  `Authorization`/`Bearer` values become `<secret>`, paths under `/home/<user>`,
  `/Users/<user>`, `C:\Users\<user>` or `/root` become `<path>`, and a line in the hub's
  credential format is dropped (security review A1838).
