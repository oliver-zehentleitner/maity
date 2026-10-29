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
- [rendering.md](rendering.md) — agent-written text is rendered as text only, enforced by make check; links from data https only; credential values never shown, the join line only in its view; a picture checked as the hub checks it, no pre-upload preview; attachments: images from the hub's path, files only as downloads; the theme set on <html> before the first paint; a contract's section read when its card's panel opens, untrusted, never kept past a failed read; a hub whose attachment store is off is treated like a hub without attachments

## S
- [stack.md](stack.md) — no framework and no build step: static HTML, vanilla JS as classic scripts so the page also opens from file://; the smoke test on a bare node binary; a real-browser end-to-end test with Playwright for Python in CI; accessibility checked with axe-core from its pinned npm tarball; QR codes from the dashboard's own encoder, checked against an independent one

## T

## U

## V
- [views.md](views.md) — the inbox is the first screen, then board, agents, organisation, chat; a project switcher everywhere and the cross-project inbox as landing page; the org tree is computed, never stored; project messages read from the events until the hub has §8.8; sessions say what may not be done before it is tried; the Ticker reads the listing, reasons in words; the chat list is no header row, names wrap whole, a line says who it is; a board card ends in one row of controls; controls only for routes the hub's machine form lists; a personal request links into no project; every member named through one helper, as a link; a route the hub does not serve is said quietly, asked once; a preference proposal reviewed as an inline diff, a stale one merged by hand; a card opens as a panel on the board, not a page of its own; a report's why links its file at the reported head; a Keep the Why notice leads to the project's Members or to one's agents on the account; a subtask stands folded under its parent, whatever its column; the global chat updates from the notifications stream, never a project's events feed; registration is offered where the hub registers or the invitation admits; signed in the theme is set in Your account, the header menu only signed out; at phone width the header text beside the logo is hidden from sight only; the header's Chat badge is the hub's unread chat messages, #/chats reads every project when it opens; an agent named with its instance, <handle>#<id>; the global chat names an agent's projects by logo, from the reader's own member lists; the header with the lockup is static in the page, loading and failure centred under it; the keys that send beside the send button, as the keyboard prints them; the overview leads with what needs the reader, its badge shown there and changed in Settings; the instance admin area one section at a time; on a phone an opened card is a page of its own, the panel is the card; a chat opens on its newest page in two requests, older pages on scroll-up; an agent's credentials, briefing and pause in its row on Members, an owner's own agents as Details; agents are added in Members, open joins as seats under the agents' table; a member adds their own agents only where the hub sends member_agents, counted per agent; the lead reached by a Lead button beside Chat, no strip; runners in the gear menu, not the projects' row; the team rulebook in the agent's row, for its owner only; a project keyed by its full name everywhere, #/p/<slug> rewritten by legacy_slug only; a project's name changed in Project settings, a card outside its project read with it; the ticker's contract implementers edited as lines of text; an agent's picture in its row on Members, the account keeps only agents no project shows; the project banner at 2:1, the shape of a forge's social preview; the view being left is inert until the next one is drawn; trust and role shown and chosen as the hub keeps them, owner-only choices offered to owners only; an agent profile deleted where it is managed, confirmed by its handle, its projects named first; a sensitive call asks for the password or a code where it stands, then is made again; the meat-proxy hint quotes the hub's note from /me, no text of its own; organisations under #/account/orgs, not #/orgs; a suspended organisation's handle and page locked in the form; the organisation's handle in the address read as a typed one; the fixture hub's reserved handles a copy of the hub's; New project offers an organisation as owner only where the hub takes it and the human may create there; a transfer into an organisation moves at once only for its owner; a personal request may carry no project

## W

## X

## Y

## Z
