# Abuse reports

Why abuse reports (`docs/api.md` §16.8, `maity_hub/reports.py`) are built the
way they are.

## The instance admin hears of a report through an account record, mailed

**Id:** 3d31dece-721f-4df2-85dc-40378b31d1df
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's ruling on the first part of the card, 2026-10-29 (an inbox record instead of a personal request, and mailed)
**Revisit when:** a request can belong to no project, or the instance has more than one admin and they need to see who of them took a report

A new report writes the account record `report_open` `{report, reason,
type}` for the instance admin. The notifications list it as an `inbox`
item while the report is open and read once it is resolved or expired,
as `registration_pending` is. Unlike that item it is mailed by the
admin's `inbox` mail mode: an abuse report should reach an admin soon,
also away from the dashboard, and only someone signed in can file one,
within the report limits. The record carries the report's id, reason
and target type, never the content.

**Rejected alternatives:**
- A personal request to every instance admin, as the contract first
  said: a request belongs to a project (`request.project_id` is not
  null), and a report on a profile has none.
- Never mailing it, as `registration_pending`: that item is never mailed
  because an anonymous registration must not trigger mail; a report is
  never anonymous.

## A report reads its target through the read paths, so a refusal is the read's `not_found`

**Id:** 442bb50d-5a43-44f2-85c3-24a3fd39878f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.8 ("what they cannot read is `not_found`, exactly as a read would answer"); the implementation of the card; for the public swarm page, the coordinator's ruling after the first part's review, 2026-10-29
**Revisit when:** a further target becomes readable outside a membership (public profiles and pages, §16.9), or an owner outside a project reads a group chat along and should report from it

A card, a message or a project is found through the reporter's
membership (`access.membership`), as their reads are, and a message
must pass `events.readable_by` with the redactions hidden. A profile is
readable when the reporter is it, owns it, or shares an active project
with it; an agent credential reaches its one project only. An agent is
also readable while a project's public swarm page shows it (an active
member of an open project with `swarm_public: on`, §6.22), named by its
id or by the global name `<owner>/<handle>` that page shows: strangers
see agents there, so with open registration that is where they report
them. Anything else answers `not_found`, the same for a target that
exists and one that does not.

**Rejected alternative:** a lookup of the target by id, then a separate
permission check: a different answer for an existing target the
reporter may not read would tell them it exists.

## The limits count the stored reports, under the account's row lock

**Id:** eb42ca24-d5b0-4a6e-b754-1f341ffc46d2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.8 (20 per account per 24 hours, 3 per target per account); the implementation of the card; for no `Retry-After` and the project's id, the coordinator's ruling after the first part's review, 2026-10-29
**Revisit when:** the reports of one account grow so many that counting a day's reports per call is slow

`POST /reports` locks the reporting account's row (an agent's owner),
counts that account's reports of the last 24 hours and of the same
target, and refuses with `rate_limited` beyond 20 or 3. The count comes
from the table, so it holds across restarts and processes, and two
reports at once cannot both pass. The 3 per target hold for good, so
that refusal sends no `Retry-After`: a client told to wait a day would
try again in vain. A project is stored and counted by its id and shown
by its full name as it is now, so a rename or a transfer neither resets
the count nor leaves the admin's view with an old name.

**Rejected alternatives:**
- An in-process limiter, as for sign-in attempts: it forgets on a
  restart and counts per process, while these limits are per account
  and a day long.
- A day's window for the 3 per target, to make the `Retry-After` of the
  first part true: the contract counts per target and account, and a
  window would let one account report the same target again every day.
- The project's full name as its key, as the first part stored it: a
  rename or a transfer changed the key.

## Retention empties a report's content and keeps the row

**Id:** e60f2edf-6222-41bf-be87-1b906bd4147a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.8 (open at most 90 days, then `expired`; the copy deleted 90 days after the report closed); the implementation of the card
**Revisit when:** an instance needs a report gone entirely, the record included

An hourly sweep (`reports.Worker`), and every read of the reports,
expires what stayed open 90 days and, 90 days after a report closed,
empties its `snapshot`, `text` and `note` (`purged_at`). The row stays
with its target, reason, status and action: the reporter's
`GET /me/reports` and the moderation record go on, without the
content. A report filed by an account that is deleted later stays as
the instance's record too; the contract keeps the copy even when its
author's account is deleted.

**Rejected alternative:** deleting the whole row at the 90-day mark: the
reporter would lose the resolution of their report, and the instance
the record that a target was reported and how it was resolved.

## The affected account hears of an action through an account record; a suspension is always mailed

**Id:** f0b94c9e-f06a-40ba-bfa7-c12f6b4e2b3a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's rulings on the second part of the card, 2026-10-29 (an account record instead of a personal request; a suspension mailed whatever the mode; an ordinary notice, no open matter)
**Revisit when:** a request can belong to no project, or a suspended account gets a way to read its notices

Every action but `dismiss` writes the account record
`moderation_applied` `{report, action, type, note}` for the account the
action concerns: an `inbox` item naming the action and the note, never
the reporter, read by a read mark as any notice, since nothing in it is
the account's to act on. It follows the `inbox` mail mode, except that a
`suspend` item is mailed at once whatever the mode says: the suspended
account signs in no more, so it reads no inbox, and the mail is the one
way it learns what happened (`Item.urgent`, `mailer._mode`).

**Rejected alternatives:**
- A personal request (§7, `info`, filed by the hub), as the contract
  first said: a request belongs to a project, and an action on a
  profile or a suspension has none; the same reason as for
  `report_open` (3d31dece-721f-4df2-85dc-40378b31d1df).
- An open matter, as `report_open` is: it would count in `inbox` and
  stay unread until closed, but the account can close nothing; only an
  instance admin lifts a hold.
- A `suspend` mail by the `inbox` mode like the other actions: under
  `off`, `hourly` or `daily` the account would not learn of it, or
  late, and has no other way in.

## Moderation changes go through narrow functions beside the routes, as the hub

**Id:** a62e70ef-8889-4c7c-98ca-b8b2726c816e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.8 ("exactly the authority its action needs over exactly the reported target"); the implementation of the card
**Revisit when:** a moderation change has to follow an ordinary write's rules that the narrow function leaves out, or organisations become a target (§6.26)

`moderation.apply` makes each change through a function beside the
route that makes it ordinarily (`routes.tasks.cancel_by_moderation`,
`routes.projects.archive_by_moderation` and `hide_by_moderation`,
`routes.events.tombstone`), with the side effects that route has:
history, the same event and audience, placements closed on archive,
takeovers reconciled. The actor is the hub with the report's id
(`event.actor_report_id`, shown as `{kind: "moderation", report_id}`),
and nobody's membership is used. A suspension is a column on the
account; `sessions.create` refuses it as a wrong password, so every way
of signing in ends there; mail sign-in counts it ineligible
(`email_sign_in._eligible`) and the suspension voids the links already
sent, so the link page and the code answer as for a dead link rather
than a raw `401`; and each place that issues a credential
(join exchange, runner pairing, device-code completion, placement
rejoin) refuses `account_suspended` itself.

**Rejected alternative:** calling the ordinary routes with a made-up
member that holds every scope: it would carry a membership the admin
does not have into history and events, and pass checks meant for
members that the contract waives only for this one change.

## Holds live in their own table, keyed by report; `hide` is the hold alone until public pages

**Id:** aab2c1b8-0a27-4bcf-832d-4f34a389e3d8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.8 ("a moderation hold"), §16.9; the coordinator asked for the `hide` part to be recorded, 2026-10-29
**Revisit when:** public profiles or pages come (§16.9): `hide` must then switch those off as well, and their writes must check the hold

`hide` and `remove` write a row in `moderation_hold` (report, target
type, stable target id, action); resolving the report again replaces
it and `dismiss` deletes it. Ordinary writes that would undo it ask
`moderation.refuse_held`: turning a project's badge or public swarm page
on, reopening an archived project or a cancelled card, renaming an agent
or uploading a picture over a reset one. Today a project is the one
target with public surfaces, so `hide` on a profile, a message or a card
changes nothing yet; its hold is what keeps them members-only once
public pages exist. A suspension is no hold: only the operator's
`maity-hub account unsuspend` lifts it, `dismiss` does not.

**Rejected alternative:** a `moderation` column on each target's table
(project, card, agent profile, human, event): a column on five tables for
one rule, and a target reported twice would keep only one
report's hold.

## A suspension takes the account lock first; every issue waits for it

**Id:** 525c4922-109b-418f-82e2-0b02b285b946
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of #663 (a race between a suspension and a credential issue), the lead's ruling, 2026-10-29; `hub/tests/test_moderation.py` `test_an_issue_waits_for_a_suspension_in_progress`

`moderation.suspend` takes the account's `account_lock` exclusively
(`account_deletion.lock_account`) before it changes anything, as a
deletion does (§2.9). `moderation.refuse_suspended` takes the same lock
shared (`write_guard.share`) and only then reads `suspended_at`. An
issue that starts while a suspension is in progress therefore waits for
it, and then refuses. The issuers (join exchange, runner pairing,
device-code completion, placement rejoin) call it before any other lock,
because the suspension, holding the account lock, goes on to lock
sessions, credentials and codes. `write_guard.hold` refuses a suspended
account as it refuses a deleted one.

**Rejected alternative:** only reading the column. A read does not wait
for an uncommitted suspension, so an issue could see the account
unsuspended, and then commit a fresh credential after the suspension has
revoked all the others.
