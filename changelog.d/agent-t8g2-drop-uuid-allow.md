### Removed

- cli: the runner no longer allows `cat /proc/sys/kernel/random/uuid` in
  Claude Code and opencode placements. In placed Claude Code sessions the
  rule never took effect (observed). The probable cause is that Claude Code
  checks a read command that names a path outside the working directories
  before its allow rules (inferred). opencode's `external_directory` deny
  likely gates the same path (not observed in an opencode session). Placed
  agents make Keep the Why Ids with `maity uuid`. Upgrade first: `maity
  uuid` ships with this release. Under Claude Code and opencode, an older
  `maity` on the runner (0.1.0a17 included) leaves placed agents with no
  UUID source, so update `maity` on each runner and restart its
  placements.
