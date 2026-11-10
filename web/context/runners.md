# Runners

## Project → Runners is the project admin's tab; refreshes redraw in place, and a missing list fails loud

**Id:** 1cf107b2-991d-42e4-aa35-9dd8f84216eb
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §15.3 and §15.4; the review of web PR #96, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** a runner's owner who is no admin asks to detach from the dashboard, or the hub sends events for runners' presence or placements

The tab is offered to owner and admin only (`members:admin`), although
the hub also lets a runner's owner detach it. A runner's owner who is no
admin of the project is left out of this tab. Allowing is the hub's grant; the
runner checks its own `[limits] projects` again. A runner the hub allows
but whose configuration does not list the project is therefore warned
about: it starts nothing here.

Presence and placements send no events, so the view re-reads every 30
seconds. A card is redrawn only when its data changed, the focus stays
on the same control, and the Allow form is rebuilt only when the set of
free runners changes, keeping the runner chosen. Detach reads the count
of agents again before it asks. A 404 on the list is an error like any
other: the dashboard ships with its hub, which has attachments.

**Reason:** a redraw every 30 seconds that rebuilds the form takes the
choice and the focus away from someone using a keyboard or a screen
reader, and an Enter after it could allow the wrong runner. A 404 that
reads as "not yet" would hide a broken route now that the hub has it.

**Rejected alternative:** the tab for every member, with Detach where
the hub allows it. In V1 that only adds a view nobody else can use, and
an Allow nobody but the admin may send. Treating a 404 as an older hub:
that was right before the hub had attachments, and today it only
covers a regression.

## Runners in the gear menu, not in the projects' row

**Id:** a6c7bf3a-9742-4535-ae21-110bd809dc47
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request (tsk-cb6myw32def0), 2026-10-27

The link to `/runners` sits in the header's gear menu, beside the
instance administration, and no longer in the row that lists the
projects. The menu marks it as the page shown.

**Reason:** a runner belongs to the person who runs it, not to a project;
the projects' row lists projects, and the gear menu holds what is not a
project's.

**Alternatives:** unknown.
