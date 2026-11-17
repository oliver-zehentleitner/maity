### Added

- cli: the runner offers the `opencode` harness (OpenCode, running Grok): a
  configuration naming `[harness.opencode]` is accepted by `maity runner check`
  and `serve` instead of refused as "not offered yet". `docs/runners.md` and
  the CLI README describe how to install and sign in as the agents' user, the
  config block, its modes and the Grok model.

### Security

- cli: opencode has no OS sandbox the runner switches on, so its command and
  permission rules are not a security boundary. Treat an opencode agent as able
  to run any command as the agents' OS user, and run opencode's agents as a
  separate OS user, isolated from the runner and the other harnesses. The owner
  accepted this residual risk (`req-kezp8rppfhn5`, "ship now, harden next"); the
  planned hardening is an OS-level sandbox for opencode (`tsk-nynpvag9zvhh`).
