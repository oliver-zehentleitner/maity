### Changed

- contract, hub: a runner's `join_failed` report takes any value in the form of the hub's error
  codes as its `detail` (`docs/api.md` §15.7): 1 to 64 characters, a lowercase letter, then
  lowercase letters, digits and `_`, the whole value with no line break. That includes a code the
  list names for another reason. Any other value is still `invalid`, and the other reasons'
  detail lists stay closed.
- cli: with `MAITY_ERROR_LINE=<32 hex digits>` in its environment, a command that fails and
  handles the failure itself ends its stderr with one line a program reads, `maity-error <those
  digits>: <code>`. For a `forbidden` with a code-form reason it is `forbidden <reason>`,
  otherwise `forbidden`. It is `network` when the hub was not reached, and `-` when the error has
  no code in that form. Maintenance and usage errors write it too. After a crash the traceback
  follows the line, so the line is not the last one and the caller reads no code; an error output
  that cannot be written gives no line either. The line is built from the error's code fields,
  never from its message. The digits are a correlation value from the caller, not a secret.
  Without the variable, nothing changes.

### Fixed

- cli: `maity runner serve` reports a failed join with the hub's reason instead of `detail: null`.
  For the pickup it is the refusal's `code` (`instance_quota`, `pickup_used`, …), and for a
  `forbidden` its `details.reason` when that has the code form (`member_join_limit`,
  `member_agents_max`, …), otherwise `forbidden`. For the join it is only the
  child's last line with the random value the runner gave it for that call, so neither the join
  URL nor text from a message or traceback becomes the detail. Without that line as the last one
  (an older `maity` on the agents' side, a crash, an error output that could not be written), it
  fails closed with `detail: null`. A pickup's 404 still carries no
  detail.
- cli: `maity runner serve` prints one line to stderr for each new state of a placement, with its
  reason, detail and generation. It holds codes and numbers only.
