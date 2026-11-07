### Changed

- web: the join panel on Agents offers "Reports to" in every case.
  - **First join by an admin:** any member who is not a guest; a boss of another owner is marked as waiting for consent, which the hub files at the exchange.
  - **A member's own agent:** oneself or one of one's own managers in the project.
  - **An agent already a member:** its current boss, changeable. The change is sent as the owner's `PATCH` before the join, and the panel says its outcome next to the join's.
- web: the owner's "Reports to" on Members and Agents also offers members of other owners, marked; saving one says it waits for consent.

### Fixed

- web: at 390 px the join panel for an agent that is already a member no longer makes the page wider than the window (the "Replace instance" select).
