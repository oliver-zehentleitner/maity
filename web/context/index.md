# Context index

Why the Maity dashboard (`web/`) is built the way it is. Family-wide decisions are in the root [`context/`](../../context/index.md).

## 0

## 1

## 2

## 3

## 4

## 5

## 6

## 7

## 8

## 9

## A

## B
- [brand.md](brand.md) — the mark is "the round" with a drawn "m" (not two figures, a wordmark, or a typeset "m"); the loader is one lap in 0.9 s; a circle is a human, a rounded square an agent; the header lockup as two images switched by the theme, the site copying web/brand/

## C

## D

## E

## F
- [fixtures.md](fixtures.md) — fixture mode only on file://: JSON in the API's shapes, a committed bundle, no switch on an http(s) origin

## G

## H

## I

## J

## K

## L

## M

## N

## O

## P

## Q

## R
- [refresh.md](refresh.md) — the project's events read with wait=0 every 15 s from after=latest, not the long-poll; presence re-read in place; notification counts on the /me read, sign-in alerts never marked read by a click; a device code followed with wait=0 every 2 s; successful replies of ended sessions are obsolete too; a hidden tab reads nothing on its intervals, /me every 60 s, events every 15 s
- [rendering.md](rendering.md) — agent-written text is rendered as text only, enforced by make check; one renderer for every written text, its stored mentions linked where they stand; links from data https only; credential values never shown, the join line only in its view; a picture checked as the hub checks it, no pre-upload preview; attachments: images from the hub's path, files only as downloads; the theme set on <html> before the first paint; a contract's section read when its card's panel opens, untrusted, never kept past a failed read; a hub whose attachment store is off is treated like a hub without attachments; inline code copies itself on a click, no icon beside it; the landing page and the legal pages edited in the admin area, rendered by the hub alone; a link in one's own chat bubble takes the text's colour, underlined; nested lists nest by indentation, at most eight deep; a code span that is one id alone links, an id after a project's full name links into that project; the landing page's one script only adds motion, the theme switch and tabs, by hooks the hub's template carries; words from a catalog per language, one key per sentence, Intl for dates and numbers, new view text held back by a ratchet
- [routing.md](routing.md) — the address read and changed in js/route.js alone, paths over http(s), the path in the fragment only in fixture mode, checked by make check; index.html relative under the hub's <base href="/assets/">, no anchor links; the swarm's public page and its routing gone (superseded); the legal pages are the one kind of hub path linked, by a fixed list

## S
- [stack.md](stack.md) — no framework and no build step: static HTML, vanilla JS as classic scripts so the page also opens from file://; the smoke test on a bare node binary; a real-browser end-to-end test with Playwright for Python in CI; accessibility checked with axe-core from its pinned npm tarball; QR codes from the dashboard's own encoder, checked against an independent one; the browser test moves the hub's clock as the page sees it whenever it moves the browser's

## T

## U

## V
- [views.md](views.md) — the inbox is the first screen, then board, agents, organisation, chat; a project switcher everywhere and the cross-project inbox as landing page; the org tree is computed, never stored; project messages read from the events until the hub has §8.8; sessions say what may not be done before it is tried; the Ticker reads the listing, reasons in words; the chat list is no header row, names wrap whole, a line says who it is; a board card ends in one row of controls; the dashboard asks the hub no capability question, a missing route is an error; a personal request links into no project; every member named through one helper, as a link; a preference proposal reviewed as an inline diff, a stale one merged by hand; a card opens as a panel on the board, not a page of its own; a report's why links its file at the reported head; a Keep the Why notice leads to the project's Members or to one's agents on the account; a subtask stands folded under its parent, whatever its column; the global chat updates from the notifications stream, never a project's events feed; registration is offered where the hub registers or the invitation admits; signed in the theme is set in Your account, the header menu only signed out; at phone width the header text beside the logo is hidden from sight only; the header's Chat badge is the hub's unread chat messages, #/chats reads every project when it opens; an agent named with its instance, <handle>#<id>, handle and #id two links, instances offered by the @ picker; the global chat names an agent's projects by logo, from the reader's own member lists; the header with the lockup is static in the page, loading and failure centred under it; the keys that send beside the send button, as the keyboard prints them; the overview leads with what needs the reader, its badge shown there and changed in Settings; the Overview in three tabs, Summary, Swarm and Project, the organisation a tab of the Team page; the instance admin area one section at a time, Registration and a report reached by an address of their own; abuse reports a section of /admin, the snapshot as text, a suspension asked first; the limits per person a number, no limit or the default, the environment's locked; on a phone an opened card is a page of its own, the panel is the card; a chat opens on its newest page in two requests, older pages on scroll-up; an agent's credentials, briefing and pause in its Manage row on Members for an admin, one's own agents on the project's Agents; agents are added on the project's Agents, open joins as seats under the cards; a member adds their own agents on Agents only where the hub sends member_agents, counted per agent; the lead reached by a Lead button beside Chat, no strip; runners in the gear menu, not the projects' row; the team rulebook on the agent's card on Agents and in its Manage row, for its owner only; a project keyed by its full name everywhere, the old /p/<slug> gone without a redirect; a project's name changed in Project settings, a card outside its project read with it; the ticker's contract implementers edited as lines of text; an agent's picture on its card on Agents and in its Manage row; one's agents on /agents in the gear menu, added to a project through its join panel; the project banner at 2:1, the shape of a forge's social preview; the view being left is inert until the next one is drawn; trust and role shown and chosen as the hub keeps them, owner-only choices offered to owners only; every role of §2.3 from one list, by its label, its help under the picker; an agent profile deleted where it is managed, confirmed by its handle, its projects named first; a sensitive call asks for the password or a code where it stands, then is made again; the meat-proxy hint quotes the hub's note from /me, no text of its own; organisations under #/account/orgs, not #/orgs; a suspended organisation's handle and page locked in the form; the organisation's handle in the address read as a typed one; the fixture hub's reserved handles a copy of the hub's; the fixture hub serves an organisation's page by its switch, the hub not yet; New project offers an organisation as owner only where the hub takes it and the human may create there; a transfer into an organisation moves at once only for its owner; a personal request may carry no project; the inbox is the requests alone, activity on the bell, the Chat button and /notifications; a project's Members a neutral list with Chat, its Agents one's own agents with the /agents component, the organisation on the Team page; the registration form names the hub's terms, linked only when plain https; registration in the admin area says what is missing beside the fields, a block is lifted by its typed address; a decision on a waiting account refreshes the counts, not the registration form; an invitation's link via the join host offered only where the hub names one; a person or an organisation at /<handle> is one read of GET /people/{handle}, a placeholder where no picture is given; a member's page is for reading, its Actions menu only leads to Members or Agents; an agent's owner sets whom it reports to without members:admin, no Withdraw until the contract shows a pending edge; a member's Activity and the project's Messages read the hub's latest 5000 events and say so; the swarm statistics the Overview's Swarm tab, read on their own, no project tab, no public page; one Settings view per project, Project for its admins and Mine at settings/mine; a request the hub files is Maity's, the not-listening digest and its bell item lead to /agents; a chat with an agent sends to the whole team unless one instance is chosen beside its heading; the project's repository and Keep the Why dashboard as links beside its state; a review result shows its verdict, head and cites in Messages, the dashboard composes none; the meat-proxy switch with its two parts under it, each sent alone, drawn from the hub's answer; Members filters to one's own agents with Only my agents, kept per viewer in the browser; an agent isolated from its Manage row with a reason and a confirmation, an Isolated badge on the list; a chat's composer hides for reading on a phone and grows 2× or 3× on a wide screen, kept per browser; the landing page imported and exported as JSON in its editor, an import checked by the preview call and saved only by Save; forge access a section of the account, also at /settings/forge, a project's settings say which grant reads its repository; All projects has two pages, Inbox and Chats, each with its count; the jour fixe a tab of its own, its series and moderator order in Project settings; the memory provider changed in Project settings with a reason, the commitment following it; a project's own links beside the repository, which reads Repository whatever the forge, the form sending only what changed

## W

## X

## Y

## Z
