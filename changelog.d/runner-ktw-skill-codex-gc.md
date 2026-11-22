### Added

- cli: a Codex placement gets the Keep the Why skill in its own skills directory
  (`<codex-home>/skills/keep-the-why/`), written from the runner's checked copy at every start;
  Codex loads it as `keep-the-why` with no setting. The Codex home stays read-only to the session
  (tsk-7casfxb7cn49).
- cli: `maity runner check` lists the Keep the Why copies the runner holds, with their commit;
  a changed or unrecorded copy is a warning.
- cli: `maity runner gc --skills` lists, and with `--yes` removes, the Keep the Why copies that no
  active placement names and no running session started with, also below the agents' home in the
  `agent_user` layout. Not on ssh hosts.
