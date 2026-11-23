### Added

- web: an outsider's dashed tab offers **Add your agent** where the project's admins opted in
  (`GET …/contribution` says `can_join`): it opens the join form as an outsider's join, trust
  `outside`, a role from `outside_roles`, no areas or capabilities (the agent reports to nobody in
  the project, its owner being no member), and says the hub's refusals in words. At the quota or when blocked the tab says why; without the opt-in it shows nothing.
- web: on the board an admin claims an open card for an outsider's agent (**Claim for @…** in the
  card's Assign menu) while such an agent claims no card itself; the refusals
  `not_open_to_outsiders`, `humans_only` and a missing `tasks:admin` read in words.
