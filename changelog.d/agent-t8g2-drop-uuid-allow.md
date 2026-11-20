### Removed

- cli: the runner no longer allows `cat /proc/sys/kernel/random/uuid` in
  Claude Code and opencode placements. The rule never took effect: Claude
  Code checks a read command that names a path outside the working
  directories before its allow rules, and opencode's `external_directory`
  deny gates the same path. Placed agents make Keep the Why Ids with
  `maity uuid`.
