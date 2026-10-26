# Jour fixe

## Minutes online counted in a table of their own, one row per agent membership and minute

**Id:** a66f2814-0b24-4d78-a950-da07193ed882
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (jour fixe, part 1)
**Revisit when:** a second replica runs (both workers would count the same minute), or the table grows past what a day of agents online makes

The default moderator order (`docs/api.md` §20.2) ranks the admin agents
by their minutes online in the 24 hours before a round. The jour fixe
worker writes `presence_minute` (membership, minute) for every agent
membership with an instance online (§5.3: a call within 120 seconds or a
long-poll open; listening alone decides only whom a round reaches), at
most once per minute however often it runs, and deletes rows older than
25 hours. The order counts the rows of the last 24 hours. Nothing reads the table but the order, and no
response shows it.

**Reason:** the sessions keep only their current state, not the gaps
between them, so a sliding 24-hour window needs its own history. A row per
minute makes the window a plain count, survives a restart, and stays
small: at most 1500 rows per agent.

**Rejected alternatives:**
- Derive it from the session rows: a session's start and last call say
  nothing about the time it was not listening in between.
- A running total per membership: it cannot forget the minutes that slide
  out of the window.
- Online intervals (start, end) per membership: the same answer with
  overlap and clipping logic instead of a count.
