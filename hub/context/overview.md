# The project overview

Why `GET /projects/{owner}/{slug}/overview` (`docs/api.md` §6.11,
`maity_hub/routes/overview.py`) is built the way it is.

## Counts and facts only, each read through the path its list uses

**Id:** 7cac9af5-d2ae-43e9-9910-15c2a79c8d44
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.11 ("Why one endpoint, and only for these three", approved by the maintainer on 2026-10-22); the implementation of the card (#590)
**Revisit when:** the overview needs a part that has a cheap source elsewhere, or the request list's visibility rule moves out of `_filtered`

The endpoint returns the board's column counts, the open requests as
counts (never a title), and the latest report per card, taken from the
card's `report` field. It repeats no member view: a reporter is
`{member_id, handle, display_name, avatar_url}`, and a deleted account is
shown as `Deleted account` (§2.9). The request counts go through the
same `_filtered` that `GET …/requests?status=open&to=all` uses, so a
count can never include a request the caller could not list.

**Reason:** each of the three parts has no cheap source otherwise. The
board would be paged through card by card, the requests page by page,
and the reports sorted in the browser. A title or a full member view
would give a second place for a visibility rule to go wrong. Reports
come from the card because the earlier ones exist only as
`task_reported` events, whose audience is limited.

**Rejected alternatives:**
- The dashboard computing the counts from the existing lists: unbounded
  paging for closed cards and for requests.
- Reports from the event log: its audience is narrower than
  `project:read`, so the overview would show different reports to
  different readers.
