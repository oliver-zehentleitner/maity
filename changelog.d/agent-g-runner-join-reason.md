### Changed

- contract, hub: a runner's `join_failed` report takes any value in the form of the hub's error
  codes as its `detail` (`docs/api.md` §15.7): 1 to 64 characters, a lowercase letter, then
  lowercase letters, digits and `_`, the whole value with no line break. That includes a code the
  list names for another reason. Any other value is still `invalid`, and the other reasons'
  detail lists stay closed.
- cli: with `MAITY_ERROR_LINE=<32 hex digits>` in its environment, a failed command ends its
  stderr with one line a program reads, `maity-error <those digits>: <code>`. For `forbidden` it
  is `forbidden <reason>`, `network` when the hub was not reached, and `-` when the error has no
  code in that form. The line comes after every failure the CLI handles, maintenance and usage
  errors included (a crash still ends with its traceback), and is built from the error's code
  fields, never from its message. Without the variable,
  nothing changes.

### Fixed

- cli: `maity runner serve` reports a failed join with the hub's reason instead of `detail: null`.
  For the pickup it is the refusal's `code`, or for a `forbidden` the rule that refused
  (`instance_quota`, `member_join_limit`, `member_agents_max`, …). For the join it is only the
  child's last line with the random value the runner gave it, so neither the join URL nor text
  from a message or traceback becomes the detail. A pickup's 404 still carries no detail.
- cli: `maity runner serve` prints one line to stderr for each new state of a placement, with its
  reason, detail and generation. It holds codes and numbers only.
