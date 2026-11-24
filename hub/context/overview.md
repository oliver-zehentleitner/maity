# The project overview

Why `GET /projects/{owner}/{slug}/overview` (`docs/api.md` §6.11,
`maity_hub/routes/overview.py`) is built the way it is.

## Counts and facts only, each read through the path its list uses

**Id:** 7cac9af5-d2ae-43e9-9910-15c2a79c8d44
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the contract PR #189 (2026-10-22), `docs/api.md` §6.11 ("Why one endpoint, and only for these three", approved by the maintainer); the implementation of the card (#590) and its review (seq 11091, the deleted reporter)
**Revisit when:** the overview needs a part that has a cheap source elsewhere, the request list's visibility rule moves out of `listed_to_all`, `relayed` and their SQL twins in `request_sql` (`plain`, `listed_to_all`, `addressed`), or a project holds so many reported cards that `latest_reports`, where the database sorts and limits the ids and only those cards are read, gets slow

The endpoint returns the board's column counts, the open requests as
counts (never a title), and the latest report per card, taken from the
card's `report` field: the database sorts the ids of the reported cards
by `reported_at` (then `updated_at`, id) and cuts them to `limit`, and
only those cards are read in full. It repeats no
member view: a reporter is
`{member_id, handle, display_name, avatar_url}`, and a deleted account is
shown as `Deleted account` (§2.9). The request counts cover exactly
what `GET …/requests?status=open&to=all` lists: one grouped statement
restates `listed_to_all` and `inbox.addressed_to`, the rest goes through
`relayed` and `listed_to_all` themselves, so a count can never include a
request the caller could not list.

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
