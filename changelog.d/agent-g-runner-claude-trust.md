### Fixed

- cli: `maity runner serve` no longer leaves a new interactive Claude Code placement waiting at
  Claude Code's "Is this a project you created or one you trust?" question in a fresh clone.
  Before the start it records the clone as trusted in the agents' Claude Code configuration
  (`projects[<clone>].hasTrustDialogAccepted`, under the lock Claude Code's own saves take), as
  an accepted question would. Like that lock, it is advisory: a runner stopped for more than 10 s
  between its last check and its write can drop a newer write to the same file. When the entry
  cannot be written, the start fails with the cause in the log instead of passing for `running`.
  The entry stays after the placement and also lets an unrestricted `claude` in that clone start
  without the question. Supervised placements need nothing.
  Checked against Claude Code 2.1.319.
- cli: `maity runner status` shows each placement's state, and for a starting or running one the
  line to attach to its session (`attach` in `--json`). Until now the supervisor kept that line
  but `status` did not print it.
