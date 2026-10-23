# Requests

## A personal request is a request row with the asker's project, hidden from every project route but the asker's

**Id:** a753a0f6-a606-43dd-86db-3431a1679721
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §7 ("Personal requests"); the hub owner's review of the schema plan, 2026-10-23 (no classification without a CHECK, `project_id` written down, `to_human` as a snapshot); implementation session, 2026-10-23
**Revisit when:** a personal request is filed that belongs to no project, profiles change hands while requests are open (§6.19 takeovers of a profile), or human notifications (§18) need their own record of it

A personal request is an ordinary `request` row with:

- `to_kind: "profile_owner"`, the profile in `to_profile` and its owner at filing time in
  `to_human`;
- `personal` true, tied to that `to_kind` by a CHECK (`personal_shape`), so no row is
  half one and half the other;
- `project_id` as the asking agent's project.

The project's request routes treat it as absent for everyone but the asker:

- the listing filters `personal = false`;
- `GET` answers only the asker; the asker's `answer` is `self_answer`;
- everything else, and every `withdraw`, is `not_found`;
- `inbox.may_answer` is false, which keeps it out of an admin agent's `to_answer` in the
  resume packet.

The human reads, answers and withdraws it through `/requests/{id}`, member of the
project or not. A non-member's answer has `answered_by` null and `answer.by` set to the
human's id. Its events carry `{id, personal, status}` only, to the asker plus the owner
when the owner is a member. It never becomes a card's `blocked_by_request`: every reader
of the card would see its id, and the card would wait on a human who may not be in the
project. A non-member's answer resolves no mentions, since resolving would hand an
outsider the members' ids (§6.2). An agent on `/requests/{id}` gets `humans_only` (§2.3).

**Reason:**
- One table keeps a personal request on the paths every request already has: the
  asker's resume, its `GET`, blocking and unblocking a card, the hub's own
  `close_request`.
- Keeping the asker's project means none of those paths needs a "no project" branch.
  `project_id` stays NOT NULL.
- `to_human` is a snapshot. The request asks the human who owned the profile when it was
  filed, and a later change of owner does not move an open request to someone who was
  never asked.

**Rejected alternatives:**
- A table of its own: a second set of answer, withdraw and event code for the same
  lifecycle.
- A nullable `project_id` for requests outside a project: every project query would need
  a `project_id IS NOT NULL` guard. Today every personal request belongs to an agent's
  project, the soul proposal and the takeover notice included.
- `personal` derived from `to_kind` alone, without the column: the hub filters on it in
  every project listing, and a boolean says that in one word. The CHECK keeps the two
  from disagreeing.
