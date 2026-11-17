### Added

- runner: each Claude Code or Codex placement gets its scratch beside its clone
  (`MAITY_SCRATCH`, with `TMPDIR` inside it), writable from the sandbox. The runner
  removes it once the hub reads the placement as closed and no session of it runs, and
  writes each removal to its log and to `removed.jsonl`. `maity runner status` shows each
  placement's clone and scratch size, and `--removed` the last removals.
  `maity runner gc --scratch [--yes]` lists and removes the scratch of placements that are
  no longer active and have no session left on the machine. Under a placement maity also reads a file the agent names in the
  scratch the runner recorded, on the same terms as in the clone.
- hub: the reviewer's and tester's role text says, where `$MAITY_SCRATCH` is set (a runner
  placement under Claude Code or Codex), to keep evidence, scratch clones and venvs there
  and to delete them after reporting.
