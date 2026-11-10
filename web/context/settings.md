# Settings

## Project settings are the project's last tab, not a panel from the gear menu

**Id:** ecbeaecb-2dcf-45ff-ae44-d8b2b455e218
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's feedback of 2026-10-25 ("project settings da oben ist komisch, das muss eher runter auf die projekt ebene, z.B. nach Runners und Why ein Settings wäre logischer", tsk-r7qja01wwzvv) and bug report (a save in Project settings landed on the inbox, tsk-t407bnycxera); the dashboard's implementation, 2026-10-25
**Revisit when:** the settings grow enough to need sub-pages, or the designer renames the tab

The project's settings are a view, `/<owner>/<slug>/settings`, shown as the
last tab of the project's row, after Runners and Why, for every member:
what one may change is a form, the rest read only. The gear menu keeps
what is not the project's (runners, instance administration). A save
redraws the route it was made on, so it stays on Settings; the
overview's Set the repository goes there at the repository field.

**Reason:** the settings belong to one project, and every other thing of
the project is a tab; a panel opened from a global menu read as the
hub's. As a panel it lived under the header of whatever view was open,
and a save, which redraws that view, closed it and left the human on
the inbox.

**Rejected alternative:** keeping the panel and reopening it after a
save: it fixes the jump but not the place the maintainer found odd.

## A project's name is changed in Project settings; a card outside its project reads with it

**Id:** 9cf859f1-d5e0-420c-9ea3-d633cea94e33
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §6.25 (rename by a human owner, transfer by the namespace owner as a consent request, aliases, card references outside a project); the card tsk-cns4d1d7ht4j from the maintainer's chat; the hub's PR #487, 2026-10-28; the card tsk-9e5cd0b0hmzx, 2026-11-04 (the step-up entered in place)
**Revisit when:** another call of the section becomes sensitive (§2.8.4), or the transfer's targets change in §6.25/§6.26

Project settings has a **Project name** section for a human owner of
the project: the full name, the earlier ones, a rename of the slug that
follows the new address, and, for the namespace owner (for an
organisation's project, each of its owners), a transfer to another
human owner of the project, into an organisation the human owns or
administers, or, out of an organisation, into the human's own
namespace (KTW e47c8d0d says which of them moves at once), with the
request withdrawable from the same place. A step-up the hub asks for
is entered in place: the transfer goes through `M.stepUp.run`, which
asks for the code in the form and sends the transfer again once it is
given; Cancel ends it without a failure. A
card's or a request's id reads `<owner>/<slug>/<id>` wherever it is shown
outside its project (`M.ids.where` says so by the view's scope), written
by one helper (`M.ids.ref`). The hub never parses the prefix (§6.25:
the id stays the identifier); the dashboard reads `<owner>/<slug>/<id>`
in written text as a link into that project (KTW 50234f88 in
`rendering.md`, `js/ids.js`).

**Reason:** the name belongs with the project's other settings and to
the people the contract gives it to; one helper keeps the prefix in one
place, as the card asked, so a later change of its form is one edit.

**Rejected alternative:** a transfer that names anyone by handle: the
contract takes only a current owner of the project or an organisation
(§6.25, §6.26), so the list offers those owners and, of the
organisations, only the ones the human owns or administers, other than
the project's own and none that is suspended.

## A member's own settings in a project are a tab of their own, My settings, at `my-settings`

**Id:** df54f284-212c-4eab-995d-778dce37f7fb
**Type:** decision
**Status:** superseded
**Superseded by:** f37bbdb4-2ad3-432e-babf-dd58f6e3ff79
**Evidence:** confirmed
**Source:** the maintainer's decision of 2026-10-29 in docs/api.md §6.2 (personal settings are the defaults, a member overrides them per project); the card tsk-32g2cjbm52ft; the coordinator's ruling on the path, 2026-10-29; the coordinator's ruling in the review of #649 (no fallback), 2026-10-30
**Revisit when:** a member's own settings for a project grow beyond a few, or the project's Settings tab is offered to every member as their own

**My settings** (`/<owner>/<slug>/my-settings`, a project view in
§16.11) shows every human member their own settings for the project:
each either **Use my default**, the value from the account sent as
`null`, or a value for this project, with what applies now. The first
is how long one of one's agent instances here may stop listening
before one hears of it. The account's notification settings hold the
default and its mode (inbox, bell or off). A failed read of a
member's settings is shown as an error; there is no quiet note for a
hub without the route (e1699490 removes that mechanism everywhere).

**Reason:** the project's Settings are kept by its owner and admins;
one member's own choices are not the project's and must not sit under
them. A tab of its own makes them reachable from inside the project,
where one thinks of that project's agents.

**Rejected alternative:** `settings/me`, under the project's Settings:
no new word for the slugs to avoid, but its tab would be marked as the
one shown and mix the owner's page with a member's own. One list of
per-project overrides on the account: far from the project it is about. A quiet "this hub has
no settings of your own per project yet" (`M.dom.notOnHub`) where the
route is missing: the hub and the dashboard ship together, and such a
note would hide a broken deploy behind words that sound normal.

## Released is a mark beside the state, never a state; Project settings say it is never cleared

**Id:** 27ca6bd9-6e83-4a85-8620-f5e9f428362f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the released mark in the dashboard (PR #659, 2026-10-29) and the Grok review of it; contract in `docs/api.md` §6.1 and §6.9
**See:** https://github.com/oliver-zehentleitner/maity — de8abccf-94dc-4947-9926-463aa13edd8f — as of 2026-10-29
**Revisit when:** §6.1 lets the mark be cleared, or the hub's released rules text changes

The hub sets `released_at` once and keeps it through every state. The
dashboard therefore shows "Released" beside the state badge, in the
header and in the overview's State row, not as a sixth state. The
tooltip carries the released rules in the hub's words, so a reader sees
what the mark binds. Project settings say the mark holds "for good"
and offer no control for it. A project without `released_at`, or a hub
that does not send it, shows no mark.

**Reason:** no call clears the mark, so a control in the settings would
promise something the hub refuses. The overview is where a reader looks
up the state, so the mark belongs there as well as in the header.

**Rejected alternatives:**
- A `released` entry in the state select: it would be lost on the next
  move back to build, which the maintainer's decision rules out.
- The mark in the header alone: the overview is where the state is read.

## A project has one Settings view: Project for its admins, Mine at settings/mine for every human member

**Id:** f37bbdb4-2ad3-432e-babf-dd58f6e3ff79
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish for only one Settings in a project (relayed on the card tsk-wzqeneerfacp, 2026-10-30); docs/api.md §16.11 after the contract #741 (the `settings` view with two tabs, the project's at `settings` for `project:admin`, the caller's own at `settings/mine` for every member, a caller without `project:admin` at `settings` gets `settings/mine`; `my-settings` is no project view any more); the alpha rule, no redirect from the old path
**Revisit when:** a member without `project:admin` needs to read a project setting the overview does not show, or one's own settings for a project grow into a page of their own
**See:** settings.md#a-members-own-settings-in-a-project-are-a-tab-of-their-own-my-settings-at-my-settings — df54f284-212c-4eab-995d-778dce37f7fb — as of 2026-10-30

The project's tabs end in one **Settings**, offered to its admins and to
every human member. Inside it two tabs, as links: **Project**
(`/<owner>/<slug>/settings`) for a member with `project:admin`, and
**Mine** (`/<owner>/<slug>/settings/mine`) for a human, one's own settings
for the project with one's default from the account. A member without
`project:admin` who opens `settings` is sent on to `settings/mine` and
sees no tab bar, having one tab. `/<owner>/<slug>/my-settings` is gone,
without a redirect.

**Reason:** two tabs called Settings and My settings side by side read as
one thing twice; one place with a part for the project and a part for
oneself is where a member looks for either.

**Rejected alternative:** keeping **My settings** as a tab of its own
(df54f284): the maintainer asked for one Settings. Showing a member the
Project tab read only, as before: the contract shows it to admins only,
and what a member may read of it (language, memory) is on the overview
or in the project's files. A redirect from `my-settings`: the alpha
rule, no route kept for an old address.

## A project's own links stand beside the repository, which reads "Repository" whatever the forge; the form sends only what changed

**Id:** 10a77061-c980-4990-b44b-cb7f518cd4eb
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-ayaav7naskbe, taken over from #846 with its review; the maintainer's decision recorded with 11b7e786, relayed by the coordinator (the repository button reads "Repository"), 2026-10-31; docs/api.md §6.11; the maintainer's request for an Actions button between Repository and Pull Requests, card tsk-kdkdy864q11r, 2026-11-10
**See:** https://github.com/oliver-zehentleitner/maity — 11b7e786-ecf7-4971-ae04-48760fd1fd41 — as of 2026-10-31
**Revisit when:** a fifth kind of link is added, or the header row has no room for the buttons on a phone
**See:** shell.md#on-a-phone-the-projects-links-are-one-row-that-scrolls-the-state-stands-beside-it — df210b31-e55a-47c9-93da-2d139e9ded89 — as of 2026-11-03

The header's row shows the repository, then Actions, then Pull Requests, then the
project's own links that are set (issues, wiki, discussions, chat, each
with its mark), then the
Keep the Why dashboard, and after them, at the right end, the state: the
maintainer asked for the state on that side and for the Pull Requests
button (tsk-hf70q6maf8cv, 2026-11-01; no reason was recorded). Unlike the
own links, Pull Requests is derived in the browser from the repository's
URL and forge, and a forge outside the table gets no button; the hub knows
only GitHub today, so the other three targets wait for it (tsk-sqpcbndm0tvd).
Actions, which the maintainer asked for (tsk-kdkdy864q11r, 2026-11-10), is
derived the same way, but only for the forges that call their workflows
Actions (GitHub, Gitea): GitLab and Bitbucket call theirs Pipelines, a word
of its own that no card has asked for yet. Its screen-reader name says the
forge ("Actions on GitHub"), as the repository's does. A second derived
button is not the "fifth kind of link" the Revisit condition below means
(an own link of §6.11, which the hub stores): it follows the forge table,
and on a phone the row still holds every button in one row that scrolls
(e2e at 390 and 360 px, light and dark). Neither derived button is on the
overview's Project tab, which shows the own links only.
Each link is plain https
only and opens in a tab of its own with `rel="noopener noreferrer"`. The
repository's button reads "Repository" for every forge. Its mark and
its name for a screen reader ("Repository on GitHub") still say which
forge. The overview's Project tab shows the same links as buttons
beside the repository. They are not in the header's list of projects:
each entry there is itself a link, which cannot hold four more, and `/me`
does not carry a project's links; §6.11 was changed to name the header
beside the project's state instead (review of #884). Project settings have four fields that send only
the links that changed; an empty field clears its link, and each refusal
of the hub is said at its field.

**Reason:** with up to six buttons in the row, the forge's name as the
label took room the four new ones need, and the mark already shows the
forge. The hub merges links by key (§6.11), so a form that sent all four
would overwrite another admin's change to a link it did not touch.

**Rejected alternatives:**
- The forge's name as the label, as before (the old header): wider, and
  it said twice what the mark says.
- Sending all four links on every save (#846): it loses another admin's
  change made meanwhile.


## The settings form says what an unset agent_owners reads now, from the page's public_page and state

**Id:** deb3b4e8-266a-42c8-ab30-6cdeeb0da50c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.1, §6.2; the card tsk-25q1kv8xwnfj; the hub's `policy.of` and `agent_owners.effective`
**Revisit when:** the project view carries the effective value or the namespace owner's suspension

The form shows an unset `agent_owners` as "Not set, follows the public page (now: …)", worked out in the page from `public_page`, `state` and `moderation`, since the hub's policy returns only the stored value. Once set the option is gone, as the hub never takes null again. The roles offered are the four bases of §6.1 and project roles on them; a role already stored stays offered, so that saving cannot drop it unseen.

**Rejected alternative:** a new hub field for the effective value: a change of contract for one sentence. The page reads a hide by moderation from the project view's `moderation`, present only while a hold stands (§16.8), and then says `members`. The cost that remains: the page does not know a suspension or deletion of the namespace owner, in which the hub reads `members` while the sentence says `anyone`.

## The public page's form appears for the namespace owner, and its link cannot know the instance's switch

**Id:** 7e873b54-6e5d-45de-b8e3-4db3621e7588
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.9, §6.26; tsk-0vccw54gj8e6
**Revisit when:** the project view carries `page_served`, as `GET /people/{handle}` does

The project's Settings show **Public page** only to the human who owns the namespace, or to an owner of the organisation that does (`GET /orgs/{handle}`, `my_role`); a slot fills when that answer comes. The account page shows **Public profile** to every human. Both say what becomes public before the switch. The project's **View public page** link shows while `public_page` is `on`, the project is not archived and it has no hold, with a note that the hub's operator must have public pages on. The profile's link follows the hub's `page_served`.

**Reason:** a project admin who is not the namespace owner would only get a refusal from the hub, because the page is published under the owner's name. The project view has no `page_served` and `MAITY_PUBLIC_PAGES` is not readable from it, so the page cannot tell whether the instance serves pages; the note says so instead of implying more.

**Rejected alternatives:** a hub field `page_served` on the project in this PR: a launch blocker should not wait for a contract change, and the card asks for the web. Fetching `?as=public` and telling the stored page from the app shell: guessing from HTML.

The profile links' form is `novalidate`: a browser's bubble on one bad address would stop the whole save, and the hub's refusals are said in words at their fields.
