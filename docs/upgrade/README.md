# Upgrade pages

Every hub release has a page here, `docs/upgrade/<version>.md`, that tells
the person running a hub what the upgrade changes and what they must do,
without reading the code. Read the page of every version between yours and
the new one, oldest first, before you upgrade
([Installing a hub, Upgrades](../install/README.md#upgrades)).

`CHANGELOG.md` lists every change of a version. The upgrade page says what
those changes mean for your hub: what you have to set, what the upgrade does
on its own and how to go back.

## How a page is written

The release pull request adds the page for its version; the release is
refused without it (`tools/upgrade_page.py`, run by ci and by the release
gate). It has these five sections, in this order, each as a second-level
heading. A section that does not apply says `Nothing.`, so a reader can tell
"nothing" from "forgotten".

The release author lists every migration and every new or changed default
since the last tag in "What happens by itself on upgrade"; the lead and ops
confirm that list before the tag is pushed.

## Template

Copy this into `docs/upgrade/<version>.md`:

```markdown
# Upgrading to <version>

From <previous version>. Released <date>. Changes in detail:
[CHANGELOG.md](../../CHANGELOG.md).

## What changes for users

What people and agents on a project notice: new or changed pages, commands,
mails, limits. One line each.

## What the operator must do

New or changed settings with their defaults, Helm values, secrets; anything to
set before the upgrade and anything to do after it (a command to run, a value
to switch on). Say for each one what happens if you do nothing.

## What happens by itself on upgrade

Every migration since the last version, and whether it only adds or also
rewrites or deletes data; data rewritten or deleted at start; keys or settings
that are removed; new mails; defaults that switch something on.

## What cannot be undone

What stays changed even if you go back to the previous image: data rewritten
or deleted, mails sent, schema the previous version refuses.

## The way back

Whether the previous image alone is enough, or the previous image together
with the dump taken before the upgrade, and when which.
```
