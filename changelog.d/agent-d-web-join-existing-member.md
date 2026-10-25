### Fixed

- web: a join for an agent that is already a member of the project no longer ends in the hub's
  "new_instance or replaces" with no way out: the join panel offers **Replace instance** (the
  member's active instances, preselected) or **Start another instance** (with the team's limit),
  leaves the membership's role, areas and briefing out of the join, and on the hub's refusal reads
  the members again and offers the same choice (docs/api.md §3.1, §6.17)
