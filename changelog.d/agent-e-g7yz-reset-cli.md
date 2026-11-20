### Added

- cli: `maity placement restart --fresh-session`, a reset from the CLI (`fresh_session: true`,
  docs/api.md §15.6) for a runner's owner or an agent with `agents:propose`; it combines with
  `--rejoin` (tsk-dqxmc1f0cxj0).

### Fixed

- runner: a live session adopted after a runner restart counts as the generation's fresh session
  (`sessions`), so a hung end later in a reset's generation resumes it instead of starting fresh
  again when the count had not reached actual.json yet (tsk-dqxmc1f0cxj0).
- runner: the `target_unknown` failure of a new generation reports that generation's `sessions`,
  not the count of the one before (tsk-dqxmc1f0cxj0).
- docs: the dashboard's **Start** asks nothing more, only **Restart** and **Reset** do; a
  **Restart** starts a fresh session today too, and **Reset** stays fresh once it resumes
  (tsk-dqxmc1f0cxj0).
