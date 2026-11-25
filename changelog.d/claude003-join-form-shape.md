### Changed

- web: the **Join an agent** form keeps one shape whether the agent joins by a line or starts
  on a runner (tsk-6w4qckma672q). Ticking **On a runner** adds the runner's fields at the end
  and hides nothing above them: take over, hand-over and the line's validity stay visible but
  switched off with a one-line reason, **Replace instance** is off with its reason (a start
  makes another instance), and a member's agents that a start cannot take stay listed, off,
  with the reason. Every field keeps its value when the part is turned on and off.
- web: an agent already in the project shows its membership (trust, role, areas, subagents,
  briefing) read-only where those fields stand, with a link to its Manage; its boss is still
  changed here, saved before the start on a runner too, and a refused start says the change
  stays saved. The form's fields follow the members' Manage in order and words.

### Fixed

- web: a start on a runner never sent the owner's subagent instruction (`subagents`,
  `subagents_language`); it now goes with a new or admitted profile's placement as with a
  join.
